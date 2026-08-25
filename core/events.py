"""
线程事件定义
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class EventType(Enum):
    """
    Worker -> GUI事件类型
    """

    FRAME = "frame"

    STATS = "stats"

    ERROR = "error"

    DEVICE_LOST = "device_lost"

    STOPPED = "stopped"



@dataclass
class CameraEvent:
    """
    摄像头事件

    type:
        事件类型

    data:
        事件数据

    message:
        错误信息
    """

    type: EventType

    data: Optional[Any] = None

    message: str = ""


def make_frame_event(frame, stats):
    return CameraEvent(
        type=EventType.FRAME,
        data={
            "frame": frame,
            "stats": stats,
        }
    )


def make_stats_event(stats):
    return CameraEvent(
        type=EventType.STATS,
        data=stats,
    )


def make_error_event(message):
    return CameraEvent(
        type=EventType.ERROR,
        message=message,
    )


def make_device_lost_event(message):
    return CameraEvent(
        type=EventType.DEVICE_LOST,
        message=message,
    )


def make_stopped_event():
    return CameraEvent(
        type=EventType.STOPPED,
    )
