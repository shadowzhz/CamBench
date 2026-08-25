"""
Camera FPS Test 全局配置
"""

SUPPORTED_FORMATS = {
    "MJPG",
    "YUYV",
    "YUY2",
}


# GUI刷新频率
PREVIEW_UPDATE_FPS = 30

# 无画面测速模式刷新频率
STATS_ONLY_UPDATE_FPS = 10


# 没有 v4l2-ctl 时使用
COMMON_FALLBACK_MODES = (
    ("MJPG", 1920, 1080, 30.0),
    ("MJPG", 1280, 720, 30.0),
    ("MJPG", 640, 480, 30.0),

    ("YUYV", 1280, 720, 30.0),
    ("YUYV", 640, 480, 30.0),
)


# 摄像头扫描路径
VIDEO_DEVICE_PATH = "/dev/video*"


# Worker相关

# 读取失败次数
MAX_FAILED_READS = 30


# 首帧等待次数
FIRST_FRAME_ATTEMPTS = 30


# 首帧等待间隔
FIRST_FRAME_INTERVAL = 0.03


# 停止线程等待时间
WORKER_STOP_TIMEOUT = 2.5


# GStreamer启动等待时间
GST_START_TIMEOUT = 1.5


# GStreamer buffer统计窗口
FPS_HISTORY_SIZE = 1000


# OpenCV预览统计窗口
PREVIEW_FPS_HISTORY_SIZE = 240
