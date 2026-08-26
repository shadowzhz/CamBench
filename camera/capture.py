import time

import cv2

from camera.pipeline import build_gstreamer_pipeline
from camera.utils import normalize_format


def read_first_frame(cap, attempts=10, stop_event=None):
    for _ in range(attempts):
        if stop_event and stop_event.is_set():
            return None

        try:
            ok, frame = cap.read()
        except Exception:
            return None

        if ok and frame is not None:
            return frame

        time.sleep(0.03)

    return None


def _close_enough(actual, requested):
    if requested <= 0:
        return True

    tolerance = max(1.0, requested * 0.05)
    return abs(actual - requested) <= tolerance


def configure_v4l2(cap, mode):
    """Apply a V4L2 mode and verify that the driver accepted it."""
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    fmt = normalize_format(mode.pixel_format)
    if fmt in ("MJPG", "YUYV"):
        cap.set(
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*fmt),
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, mode.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, mode.height)
    cap.set(cv2.CAP_PROP_FPS, mode.fps)

    actual_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    actual_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    actual_fps = cap.get(cv2.CAP_PROP_FPS)

    size_ok = (
        int(round(actual_width)) == mode.width
        and int(round(actual_height)) == mode.height
    )
    fps_ok = _close_enough(actual_fps, mode.fps)

    return {
        "width": actual_width,
        "height": actual_height,
        "fps": actual_fps,
        "accepted": size_ok and fps_ok,
    }


def open_gstreamer_capture(camera, mode, errors, stop_event=None):
    for device in camera.device_candidates:
        for io in (True, False):
            if stop_event and stop_event.is_set():
                return None, "", None, ""

            pipeline = build_gstreamer_pipeline(device, mode, io)
            cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            label = f"GStreamer {device}"

            if not cap.isOpened():
                errors.append(f"{label}: open failed")
                cap.release()
                continue

            frame = read_first_frame(cap, stop_event=stop_event)
            if frame is not None:
                print(
                    f"capture backend=GStreamer device={device} "
                    f"mode={mode.width}x{mode.height}@{mode.fps:g} {normalize_format(mode.pixel_format)}"
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
            return cap, f"OpenCV V4L2 {device}", frame, device

        errors.append(f"OpenCV V4L2 {device}: no frame")
        cap.release()

    return None, "", None, ""


def open_capture(camera, mode, stop_event=None):
    errors = []
    fmt = normalize_format(mode.pixel_format)

    # 120 FPS 及以上的 MJPG 强制优先使用 GStreamer，避免 OpenCV
    # V4L2 路径对高帧率 MJPG 解码造成约 100 FPS 的瓶颈。
    if fmt == "MJPG" and mode.fps >= 120:
        result = open_gstreamer_capture(camera, mode, errors, stop_event)
        if result[0]:
            return (*result, errors)

    # 其余模式保持 V4L2 直接打开优先。
    result = open_v4l2_capture(camera, mode, errors, stop_event)
    if result[0]:
        return (*result, errors)

    # V4L2 无法取帧时再使用 GStreamer，保留原有 fallback。
    result = open_gstreamer_capture(camera, mode, errors, stop_event)
    if result[0]:
        return (*result, errors)

    return None, "", None, "", errors
