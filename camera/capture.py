import threading
import time
from collections import deque

import cv2
import gi
import numpy as np

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from camera.pipeline import (
    build_gstreamer_pipeline,
    build_high_fps_preview_pipeline,
    build_native_gstreamer_pipeline,
)
from camera.utils import normalize_format
from core import log

Gst.init(None)

# 源端 FPS 统计窗口(帧):窗口内算瞬时帧率,1000 帧足够平滑
SOURCE_FPS_WINDOW = 1000


def read_first_frame(cap, attempts=100, stop_event=None):
    """阻塞读取第一帧;只用于确认设备可用,不作为测速数据。"""
    for _ in range(attempts):
        if stop_event and stop_event.is_set():
            return None
        if isinstance(cap, NativeGStreamerCapture):
            error = cap.poll_error()
            if error:
                raise RuntimeError(error)
        ok, frame = cap.read()
        if ok and frame is not None:
            return frame
        time.sleep(0.02)
    return None


def _close_enough(actual, requested):
    # 部分驱动会把 FPS 取整或返回 29.97 这类值,留 5% 容差避免把合法模式误判为被拒
    if requested <= 0:
        return True
    tolerance = max(1.0, requested * 0.05)
    return abs(actual - requested) <= tolerance


def configure_v4l2(cap, mode):
    """按目标模式设置 OpenCV V4L2 参数,返回实际生效的分辨率/FPS。"""
    # 必须先设 FOURCC 锁定 MJPG/YUYV,再设分辨率和 FPS:
    # OpenCV 默认按未压缩格式协商,顺序反了高帧率模式根本不会出现在可选项里
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


class NativeGStreamerCapture:
    """通过 GStreamer appsink 采集,帧为 numpy BGR/BGRx 数组。"""

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
            raise RuntimeError("GStreamer 管线无法进入 PLAYING 状态")
        result, state, _pending = self.pipeline.get_state(5 * Gst.SECOND)
        if result == Gst.StateChangeReturn.FAILURE or state != Gst.State.PLAYING:
            raise RuntimeError(f"GStreamer 管线状态异常: {state.value_nick}")
        error = self.poll_error()
        if error:
            raise RuntimeError(error)

    def poll_error(self):
        """取出总线上最新的错误消息,无错误返回 None。"""
        bus = self.pipeline.get_bus()
        if bus is None:
            return None
        message = bus.pop_filtered(Gst.MessageType.ERROR)
        if message is None:
            return None
        error, debug = message.parse_error()
        detail = str(error)
        if debug:
            detail += f" ({debug})"
        return f"GStreamer ERROR: {detail}"

    def isOpened(self):
        return not self._released

    def read(self):
        if self._released:
            return False, None
        sample = self.appsink.emit("try-pull-sample", Gst.SECOND // 2)
        if sample is None:
            error = self.poll_error()
            if error:
                raise RuntimeError(error)
            return False, None

        buffer = sample.get_buffer()
        success, mapped = buffer.map(Gst.MapFlags.READ)
        if not success:
            return False, None
        try:
            expected_size = self.width * self.height * self.channels
            if len(mapped.data) < expected_size:
                return False, None
            frame = np.frombuffer(
                mapped.data, dtype=np.uint8, count=expected_size
            ).reshape((self.height, self.width, self.channels))
            # BGRx 帧去掉 alpha 通道;copy 避免引用已被 GStreamer 复用的内存
            if self.channels == 4:
                return True, frame[:, :, :3].copy()
            return True, frame.copy()
        finally:
            buffer.unmap(mapped)

    def release(self):
        if self._released:
            return
        self._released = True
        self.pipeline.set_state(Gst.State.NULL)


class HighFpsGStreamerCapture(NativeGStreamerCapture):
    """在 v4l2src 源端统计 FPS 的高帧率采集,GUI 预览刷新不影响统计。"""

    def __init__(self, pipeline, width, height, channels=3):
        super().__init__(pipeline, width, height, channels=channels)
        source = pipeline.get_by_name("cambenchsrc")
        if source is None:
            raise RuntimeError("找不到高帧率 v4l2src")
        pad = source.get_static_pad("src")
        if pad is None:
            raise RuntimeError("找不到高帧率 v4l2src src pad")

        self._counter = 0
        self._timestamps = deque(maxlen=SOURCE_FPS_WINDOW)
        self._lock = threading.Lock()
        self._counter_pad = pad
        # probe 挂在 v4l2src 的输出上:统计的是摄像头实际发出的帧,
        # 而不是经过解码、预览之后还剩多少
        self._probe_id = pad.add_probe(Gst.PadProbeType.BUFFER, self._count_buffer)

    def _count_buffer(self, _pad, _info):
        now = time.perf_counter()
        with self._lock:
            self._counter += 1
            self._timestamps.append(now)
        return Gst.PadProbeReturn.OK

    def reset_source_stats(self):
        """清除启动阶段的 buffer,正式测速从此刻开始。"""
        with self._lock:
            self._counter = 0
            self._timestamps.clear()

    def source_stats(self):
        """返回 (总帧数, 源端实时 FPS)。"""
        with self._lock:
            count = self._counter
            timestamps = list(self._timestamps)
        if len(timestamps) < 2:
            return count, 0.0
        elapsed = timestamps[-1] - timestamps[0]
        if elapsed <= 0:
            return count, 0.0
        return count, (len(timestamps) - 1) / elapsed

    def release(self):
        if self._released:
            return
        try:
            self._counter_pad.remove_probe(self._probe_id)
        except Exception:
            pass
        super().release()


def open_high_fps_gstreamer_capture(camera, mode, errors, stop_event=None):
    for device in camera.device_candidates:
        if stop_event and stop_event.is_set():
            return None, "", None, ""
        pipeline = None
        cap = None
        try:
            description = build_high_fps_preview_pipeline(device, mode)
            log(f"GStreamer 高帧率管线: {description}")
            pipeline = Gst.parse_launch(description)
            channels = 4 if "format=BGRx" in description else 3
            cap = HighFpsGStreamerCapture(pipeline, mode.width, mode.height, channels=channels)
            cap.start()
            frame = read_first_frame(cap, stop_event=stop_event)
            if frame is not None:
                # 首帧只用于确认管线和图像尺寸,不作为正式测速数据。
                cap.reset_source_stats()
                log(
                    f"capture backend=GStreamer-high-FPS device={device} "
                    f"mode={mode.width}x{mode.height}@{mode.fps:g} "
                    f"{normalize_format(mode.pixel_format)} "
                    f"actual={frame.shape[1]}x{frame.shape[0]}"
                )
                return cap, f"GStreamer high-FPS {device}", frame, device
            error = cap.poll_error()
            errors.append(f"GStreamer 高帧率 {device}: {error or '无画面'}")
            cap.release()
        except Exception as exc:
            errors.append(f"GStreamer 高帧率 {device}: {exc}")
            if cap is not None:
                cap.release()
            elif pipeline is not None:
                pipeline.set_state(Gst.State.NULL)
    return None, "", None, ""


def open_native_gstreamer_capture(camera, mode, errors, stop_event=None):
    for device in camera.device_candidates:
        if stop_event and stop_event.is_set():
            return None, "", None, ""
        pipeline = None
        try:
            description = build_native_gstreamer_pipeline(device, mode)
            log(f"GStreamer 原生管线: {description}")
            pipeline = Gst.parse_launch(description)
            cap = NativeGStreamerCapture(pipeline, mode.width, mode.height, channels=4)
            cap.start()
            frame = read_first_frame(cap, stop_event=stop_event)
            if frame is not None:
                log(
                    f"capture backend=GStreamer-native device={device} "
                    f"mode={mode.width}x{mode.height}@{mode.fps:g} "
                    f"{normalize_format(mode.pixel_format)} "
                    f"actual={frame.shape[1]}x{frame.shape[0]}"
                )
                return cap, f"GStreamer native {device}", frame, device
            errors.append(f"GStreamer 原生 {device}: 无画面")
            cap.release()
        except Exception as exc:
            errors.append(f"GStreamer 原生 {device}: {exc}")
            if pipeline is not None:
                pipeline.set_state(Gst.State.NULL)
    return None, "", None, ""


def open_gstreamer_capture(camera, mode, errors, stop_event=None):
    """经 OpenCV 的 GStreamer 后端采集(管线字符串由 pipeline 模块给出)。"""
    for device in camera.device_candidates:
        for io_mode in (True, False):
            if stop_event and stop_event.is_set():
                return None, "", None, ""
            try:
                pipeline = build_gstreamer_pipeline(device, mode, io_mode)
                cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            except Exception as exc:
                errors.append(f"GStreamer {device}: {exc}")
                continue

            label = f"GStreamer {device}"
            if not cap.isOpened():
                errors.append(f"{label}: 打开失败")
                cap.release()
                continue

            frame = read_first_frame(cap, stop_event=stop_event)
            if frame is not None:
                log(
                    f"capture backend=GStreamer device={device} "
                    f"mode={mode.width}x{mode.height}@{mode.fps:g} "
                    f"{normalize_format(mode.pixel_format)} "
                    f"actual={frame.shape[1]}x{frame.shape[0]}"
                )
                return cap, label, frame, device
            errors.append(f"{label}: 无画面")
            cap.release()
    return None, "", None, ""


def open_v4l2_capture(camera, mode, errors, stop_event=None):
    for device in camera.device_candidates:
        if stop_event and stop_event.is_set():
            return None, "", None, ""
        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not cap.isOpened():
            errors.append(f"OpenCV V4L2 {device}: 打开失败")
            cap.release()
            continue

        negotiated = configure_v4l2(cap, mode)
        if not negotiated["accepted"]:
            errors.append(
                f"OpenCV V4L2 {device}: 模式被拒绝 "
                f"请求={mode.width}x{mode.height}@{mode.fps:.2f}, "
                f"实际={negotiated['width']:.0f}x{negotiated['height']:.0f}@{negotiated['fps']:.2f}"
            )
            cap.release()
            continue

        frame = read_first_frame(cap, stop_event=stop_event)
        if frame is not None:
            log(
                f"capture backend=V4L2 device={device} "
                f"mode={mode.width}x{mode.height}@{mode.fps:g} "
                f"{normalize_format(mode.pixel_format)} "
                f"actual={negotiated['width']:.0f}x{negotiated['height']:.0f}@{negotiated['fps']:.2f}"
            )
            return cap, f"OpenCV V4L2 {device}", frame, device
        errors.append(f"OpenCV V4L2 {device}: 无画面")
        cap.release()
    return None, "", None, ""


def open_capture(camera, mode, stop_event=None):
    """
    按模式选择采集后端,返回 (cap, backend, 首帧, device, errors)。

    - MJPG >= 120 FPS:只走原生 GStreamer 管线;失败时不回退到
      OpenCV V4L2,避免把高帧率模式重新限制在低帧率。
    - MJPG >= 30 FPS:优先 GStreamer,避免 OpenCV 内部 JPEG 解码
      成为瓶颈(部分内置摄像头会因此掉到约 15 FPS)。
    - 其他模式:先 OpenCV V4L2,失败后再试 GStreamer。
    """
    errors = []
    fmt = normalize_format(mode.pixel_format)

    if fmt == "MJPG" and mode.fps >= 120:
        result = open_high_fps_gstreamer_capture(camera, mode, errors, stop_event)
        if result[0]:
            return (*result, errors)
        errors.append("高帧率 MJPG 的原生 GStreamer 管线启动失败,已禁止 V4L2 伪回退")
        return None, "", None, "", errors

    if fmt == "MJPG" and mode.fps >= 30:
        result = open_gstreamer_capture(camera, mode, errors, stop_event)
        if result[0]:
            return (*result, errors)

    result = open_v4l2_capture(camera, mode, errors, stop_event)
    if result[0]:
        return (*result, errors)
    result = open_gstreamer_capture(camera, mode, errors, stop_event)
    if result[0]:
        return (*result, errors)
    return None, "", None, "", errors
