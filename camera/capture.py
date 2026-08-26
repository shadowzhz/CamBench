import time

import cv2
import gi
import numpy as np

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from camera.pipeline import build_gstreamer_pipeline, build_native_gstreamer_pipeline
from camera.pipeline import has_accelerated_jpeg_decoder
from camera.utils import normalize_format


Gst.init(None)


def read_first_frame(cap, attempts=30, stop_event=None):
    for _ in range(attempts):
        if stop_event and stop_event.is_set():
            return None
        try:
            ok, frame = cap.read()
        except Exception:
            return None
        if ok and frame is not None:
            return frame
        time.sleep(0.01)
    return None


def _close_enough(actual, requested):
    if requested <= 0:
        return True
    tolerance = max(1.0, requested * 0.05)
    return abs(actual - requested) <= tolerance


def configure_v4l2(cap, mode):
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    fmt = normalize_format(mode.pixel_format)
    if fmt in ("MJPG", "YUYV", "YUY2"):
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fmt))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, mode.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, mode.height)
    cap.set(cv2.CAP_PROP_FPS, mode.fps)
    actual_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    actual_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    return {
        "width": actual_width,
        "height": actual_height,
        "fps": actual_fps,
        "accepted": (
            int(round(actual_width)) == mode.width
            and int(round(actual_height)) == mode.height
            and _close_enough(actual_fps, mode.fps)
        ),
    }


class _NativeGStreamerCapture:
    def __init__(self, pipeline, width, height, channels=4):
        self.pipeline = pipeline
        self.appsink = pipeline.get_by_name("cambenchsink")
        if self.appsink is None:
            raise RuntimeError("找不到 CamBench GStreamer appsink")
        self.width = width
        self.height = height
        self.channels = channels
        self._released = False

    def start(self):
        result = self.pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("GStreamer 管道无法进入 PLAYING 状态")
        result, state, _pending = self.pipeline.get_state(5 * Gst.SECOND)
        if result == Gst.StateChangeReturn.FAILURE or state != Gst.State.PLAYING:
            raise RuntimeError(f"GStreamer 管道状态异常: {state.value_nick}")

    def isOpened(self):
        return not self._released

    def read(self):
        if self._released:
            return False, None
        sample = self.appsink.emit("try-pull-sample", Gst.SECOND // 2)
        if sample is None:
            return False, None
        buffer = sample.get_buffer()
        success, mapped = buffer.map(Gst.MapFlags.READ)
        if not success:
            return False, None
        try:
            expected_size = self.width * self.height * self.channels
            if len(mapped.data) < expected_size:
                return False, None
            frame = np.frombuffer(mapped.data, dtype=np.uint8, count=expected_size).reshape(
                (self.height, self.width, self.channels)
            )
            return True, frame[:, :, :3].copy()
        finally:
            buffer.unmap(mapped)

    def release(self):
        if self._released:
            return
        self._released = True
        self.pipeline.set_state(Gst.State.NULL)


def open_native_gstreamer_capture(camera, mode, errors, stop_event=None):
    for device in camera.device_candidates:
        if stop_event and stop_event.is_set():
            return None, "", None, ""
        pipeline = None
        try:
            description = build_native_gstreamer_pipeline(device, mode)
            print(f"GStreamer native pipeline: {description}")
            pipeline = Gst.parse_launch(description)
            cap = _NativeGStreamerCapture(pipeline, mode.width, mode.height, channels=4)
            cap.start()
            frame = read_first_frame(cap, stop_event=stop_event)
            if frame is not None:
                print(
                    f"capture backend=GStreamer-native device={device} "
                    f"mode={mode.width}x{mode.height}@{mode.fps:g} "
                    f"{normalize_format(mode.pixel_format)} "
                    f"actual={frame.shape[1]}x{frame.shape[0]}"
                )
                return cap, f"GStreamer native {device}", frame, device
            errors.append(f"GStreamer native {device}: no frame")
            cap.release()
        except Exception as exc:
            errors.append(f"GStreamer native {device}: {exc}")
            if pipeline is not None:
                try:
                    pipeline.set_state(Gst.State.NULL)
                except Exception:
                    pass
    return None, "", None, ""


def open_gstreamer_capture(camera, mode, errors, stop_event=None):
    for device in camera.device_candidates:
        for io in (True, False):
            if stop_event and stop_event.is_set():
                return None, "", None, ""
            try:
                pipeline = build_gstreamer_pipeline(device, mode, io)
                cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            except Exception as exc:
                errors.append(f"GStreamer {device}: {exc}")
                continue
            label = f"GStreamer {device}"
            if not cap.isOpened():
                errors.append(f"{label}: open failed")
                cap.release()
                continue
            frame = read_first_frame(cap, stop_event=stop_event)
            if frame is not None:
                print(
                    f"capture backend=GStreamer device={device} "
                    f"mode={mode.width}x{mode.height}@{mode.fps:g} "
                    f"{normalize_format(mode.pixel_format)} "
                    f"actual={frame.shape[1]}x{frame.shape[0]}"
                )
                return cap, label, frame, device
            errors.append(f"{label}: no frame")
            cap.release()
    return None, "", None, ""


def open_v4l2_capture(camera, mode, errors, stop_event=None):
    for device in camera.device_candidates:
        if stop_event and stop_event.is_set():
            return None, "", None, ""
        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not cap.isOpened():
            errors.append(f"OpenCV V4L2 {device}: open failed")
            cap.release()
            continue
        negotiated = configure_v4l2(cap, mode)
        if not negotiated["accepted"]:
            errors.append(
                f"OpenCV V4L2 {device}: mode rejected "
                f"requested={mode.width}x{mode.height}@{mode.fps:.2f}, "
                f"actual={negotiated['width']:.0f}x{negotiated['height']:.0f}"
                f"@{negotiated['fps']:.2f}"
            )
            cap.release()
            continue
        frame = read_first_frame(cap, stop_event=stop_event)
        if frame is not None:
            print(
                f"capture backend=V4L2 device={device} "
                f"mode={mode.width}x{mode.height}@{mode.fps:g} "
                f"{normalize_format(mode.pixel_format)} "
                f"actual={negotiated['width']:.0f}x{negotiated['height']:.0f}"
                f"@{negotiated['fps']:.2f}"
            )
            return cap, f"OpenCV V4L2 {device}", frame, device
        errors.append(f"OpenCV V4L2 {device}: no frame")
        cap.release()
    return None, "", None, ""


def open_capture(camera, mode, stop_event=None):
    errors = []
    fmt = normalize_format(mode.pixel_format)
    if fmt == "MJPG" and mode.fps >= 120:
        # Without an accelerated JPEG decoder, probing software jpegdec at
        # high FPS is both unreliable and noisy. Prefer the V4L2 path, which
        # can negotiate the camera's native MJPG frame rate directly.
        if not has_accelerated_jpeg_decoder():
            result = open_v4l2_capture(camera, mode, errors, stop_event)
            if result[0]:
                return (*result, errors)
            errors.append("No accelerated JPEG decoder; V4L2 high-FPS MJPG fallback failed")
        else:
            result = open_native_gstreamer_capture(camera, mode, errors, stop_event)
            if result[0]:
                return (*result, errors)
            errors.append("Native GStreamer high-FPS MJPG unavailable; falling back to OpenCV GStreamer")
            result = open_gstreamer_capture(camera, mode, errors, stop_event)
            if result[0]:
                return (*result, errors)
            errors.append("GStreamer high-FPS MJPG unavailable; falling back to V4L2")
    result = open_v4l2_capture(camera, mode, errors, stop_event)
    if result[0]:
        return (*result, errors)
    result = open_gstreamer_capture(camera, mode, errors, stop_event)
    if result[0]:
        return (*result, errors)
    return None, "", None, "", errors
