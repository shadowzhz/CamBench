"""公共件:全局配置、Worker->GUI 事件、线程安全日志。"""

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------- 日志

_log_lock = threading.Lock()


def log(message):
    timestamp = time.strftime("%H:%M:%S")
    with _log_lock:
        print(f"[{timestamp}] {message}", flush=True)


# ---------------------------------------------------------------- 配置

# 采集支持的像素格式
SUPPORTED_FORMATS = {"MJPG", "YUYV", "YUY2"}

# GUI 刷新频率
PREVIEW_UPDATE_FPS = 30

# 无画面测速模式刷新频率
STATS_ONLY_UPDATE_FPS = 10

# OpenCV 预览的 FPS 统计窗口
PREVIEW_FPS_HISTORY_SIZE = 240

# 实测 FPS 低于标称值该比例时,视为"跑不满"
LOW_FPS_RATIO_THRESHOLD = 0.7

# 连续多少次统计低于阈值后给出诊断提示
LOW_FPS_SUSTAINED_UPDATES = 15

# 低于该标称帧率的模式不做"跑不满"判定
LOW_FPS_MIN_TARGET = 30.0

# 个别驱动不支持帧间隔枚举时,兜底通告的常见模式
COMMON_FALLBACK_MODES = (
    ("MJPG", 1920, 1080, 30.0),
    ("MJPG", 1280, 720, 30.0),
    ("MJPG", 640, 480, 30.0),
    ("YUYV", 1280, 720, 30.0),
    ("YUYV", 640, 480, 30.0),
)


# ---------------------------------------------------------------- 事件

class EventType(Enum):
    FRAME = "frame"
    STATS = "stats"
    ERROR = "error"
    DEVICE_LOST = "device_lost"
    STOPPED = "stopped"
    DIAGNOSTICS = "diagnostics"


@dataclass
class CameraEvent:
    type: EventType
    data: Optional[Any] = None
    message: str = ""


def make_frame_event(frame, stats):
    return CameraEvent(type=EventType.FRAME, data={"frame": frame, "stats": stats})


def make_stats_event(stats):
    return CameraEvent(type=EventType.STATS, data=stats)


def make_error_event(message):
    return CameraEvent(type=EventType.ERROR, message=message)


def make_device_lost_event(message):
    return CameraEvent(type=EventType.DEVICE_LOST, message=message)


def make_stopped_event():
    return CameraEvent(type=EventType.STOPPED)


def make_diagnostics_event(message):
    return CameraEvent(type=EventType.DIAGNOSTICS, message=message)
