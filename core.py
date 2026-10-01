"""
公共核心模块: 全局配置、跨线程事件总线 (Event-Driven) 与线程安全日志。

【架构设计说明】
本项目采用"采集与渲染解耦"的双线程/多线程模型:
1. GUI 线程 (主线程):
   - 运行 Tkinter 窗口主循环，不允许直接调用任何阻塞式 I/O 或 OpenCV 耗时读帧函数;
   - 每 20ms (50Hz) 从线程安全队列读取一次最新事件并刷新界面控件。
2. 采集 Worker 线程 (PreviewWorker):
   - 负责死循环全速调用底层驱动/GStreamer 读取数据帧;
   - 计算高精度瞬时与平均 FPS;
   - 按固定频率 (默认 30Hz) 封装 Event 对象投递到 GUI 队列;
   - 使用 put_nowait (队列满即丢弃旧帧)，确保采集端永远不会被慢速 GUI 渲染反向拖垮。
3. 热插拔监听线程 (DeviceMonitor):
   - 负责监听系统设备节点变动，发现插拔后发布 DEVICES_CHANGED 事件。
"""

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

# 采集支持的像素格式(主要为常用高吞吐压缩格式与无损原始格式)
SUPPORTED_FORMATS = {"MJPG", "YUYV", "YUY2"}

# GUI 预览刷新频率: 限制界面图片重绘频率为 30 FPS，避免消耗过多 CPU 占用
PREVIEW_UPDATE_FPS = 30

# 无画面纯测速模式刷新频率: 仅刷新数字面板，进一步节约资源
STATS_ONLY_UPDATE_FPS = 10

# OpenCV 预览的 FPS 滚动统计窗口大小 (帧数)
PREVIEW_FPS_HISTORY_SIZE = 240

# 实测 FPS 低于标称值该比例 (如 30fps 跑出不足 21fps) 时视为"跑不满"
LOW_FPS_RATIO_THRESHOLD = 0.7

# 连续低于阈值多少次采样后，在界面触发黄色诊断引导提示
LOW_FPS_SUSTAINED_UPDATES = 15

# 标称帧率低于此值 (如 <=15fps) 时不作"跑不满"告警判定
LOW_FPS_MIN_TARGET = 30.0

# 部分老旧/私有驱动不支持 V4L2 帧间隔 ioctl 枚举时的通用候选兜底模式
COMMON_FALLBACK_MODES = (
    ("MJPG", 1920, 1080, 30.0),
    ("MJPG", 1280, 720, 30.0),
    ("MJPG", 640, 480, 30.0),
    ("YUYV", 1280, 720, 30.0),
    ("YUYV", 640, 480, 30.0),
)


# ---------------------------------------------------------------- 事件

class EventType(Enum):
    FRAME = "frame"                  # 携带最新图像帧及实时性能统计
    STATS = "stats"                  # 仅携带性能统计指标(无图像)
    ERROR = "error"                  # 采集或驱动层错误消息
    DEVICE_LOST = "device_lost"      # 当前运行中的设备被意外拔出/离线
    STOPPED = "stopped"              # 采集线程已安全退出
    DIAGNOSTICS = "diagnostics"      # 硬件瓶颈诊断报告结果
    DEVICES_CHANGED = "devices_changed"  # 系统拓扑变动(新相机插入或移除)


@dataclass
class CameraEvent:
    """跨线程通信事件载荷模型。"""
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


def make_devices_changed_event(added=None, removed=None):
    return CameraEvent(
        type=EventType.DEVICES_CHANGED,
        data={"added": added or [], "removed": removed or []},
    )
