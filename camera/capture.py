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


def configure_v4l2(cap, mode):
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

        configure_v4l2(cap, mode)

        frame = read_first_frame(cap, stop_event=stop_event)

        if frame is not None:
            return cap, f"OpenCV V4L2 {device}", frame, device

        errors.append(f"OpenCV V4L2 {device}: no frame")
        cap.release()

    return None, "", None, ""


def open_capture(camera, mode, stop_event=None):
    errors = []

    # V4L2 直接打开优先。部分笔记本内置摄像头对 GStreamer
    # 的 v4l2src 协商不稳定，但 OpenCV 的 V4L2 backend 可以正常取帧。
    result = open_v4l2_capture(camera, mode, errors, stop_event)
    if result[0]:
        return (*result, errors)

    # V4L2 无法取帧时再使用 GStreamer，兼容外接相机及特殊格式。
    result = open_gstreamer_capture(camera, mode, errors, stop_event)
    if result[0]:
        return (*result, errors)

    return None, "", None, "", errors
