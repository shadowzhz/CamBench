import re
from fractions import Fraction

from core import COMMON_FALLBACK_MODES, SUPPORTED_FORMATS

from camera.models import CameraMode
from camera.utils import normalize_format, run_cmd
from camera.v4l2_io import enumerate_device_modes


def fps_fraction(fps):
    """把浮点帧率转成 V4L2 caps 使用的分数形式,如 29.97 -> 30000/1001。"""
    if abs(fps - round(fps)) < 0.01:
        return int(round(fps)), 1

    for value, numerator in (
        (23.976, 24000),
        (29.97, 30000),
        (59.94, 60000),
        (119.88, 120000),
    ):
        if abs(fps - value) < 0.02:
            return numerator, 1001

    fraction = Fraction(fps).limit_denominator(1001)
    return fraction.numerator, fraction.denominator


def _modes_from_ioctl(device):
    """
    直接通过 V4L2 ioctl 枚举模式。

    设备无法打开(ioctl 不可用)时返回 None,由调用方回退到
    v4l2-ctl 文本解析;设备可打开时结果即为权威。
    """
    raw_modes = enumerate_device_modes(device)
    if raw_modes is None:
        return None

    modes = []
    for code, width, height, fps in raw_modes:
        if code not in SUPPORTED_FORMATS:
            continue
        modes.append(CameraMode(code, width, height, fps))
    return modes


def _modes_from_v4l2ctl(device):
    """解析 v4l2-ctl --list-formats-ext 文本输出(回退路径)。"""
    text = run_cmd(["v4l2-ctl", "-d", device, "--list-formats-ext"])

    modes = []
    current_format = None
    width = None
    height = None

    format_pattern = re.compile(r"\[\d+\]:\s*'([^']+)'")
    size_pattern = re.compile(r"Size:\s*Discrete\s+(\d+)x(\d+)")
    fps_pattern = re.compile(r"\(([\d.]+)\s+fps\)")

    for raw in text.splitlines():
        line = raw.strip()

        m = format_pattern.search(line)
        if m:
            current_format = m.group(1).upper()
            continue

        m = size_pattern.search(line)
        if m:
            width = int(m.group(1))
            height = int(m.group(2))
            continue

        m = fps_pattern.search(line)
        if not m:
            continue
        if current_format not in SUPPORTED_FORMATS or width is None:
            continue

        modes.append(
            CameraMode(current_format, width, height, float(m.group(1)))
        )

    return modes


def _finalize_modes(modes):
    """去重并排序:MJPG 优先,然后按像素数、帧率从高到低。"""
    unique = {}
    for mode in modes:
        key = (
            normalize_format(mode.pixel_format),
            mode.width,
            mode.height,
            round(mode.fps, 3),
        )
        unique[key] = mode

    result = list(unique.values())
    result.sort(
        key=lambda x: (
            0 if normalize_format(x.pixel_format) == "MJPG" else 1,
            -(x.width * x.height),
            -x.fps,
        )
    )
    return tuple(result)


def get_camera_modes(device):
    """ioctl 枚举优先;设备无法直接访问时回退到 v4l2-ctl 文本解析。"""
    modes = _modes_from_ioctl(device)
    if modes is None:
        modes = _modes_from_v4l2ctl(device)
    return _finalize_modes(modes)


def fallback_modes():
    return tuple(
        CameraMode(fmt, w, h, fps) for fmt, w, h, fps in COMMON_FALLBACK_MODES
    )
