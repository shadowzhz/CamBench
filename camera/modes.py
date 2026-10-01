"""
摄像头采集模式(格式/分辨率/帧率)枚举与分级组织模块。

职责:
1. 底层枚举: 在 Linux 下优先通过 V4L2 ioctl 原语查询硬件模式，备用 v4l2-ctl 文本解析；在 Windows 下调用 DirectShow/MSMF 探测；
2. 排序与规范化: 将驱动返回的乱序模式按 MJPG 优先、像素面积降序、帧率降序规范化排序；
3. 分级组织索引: 提供 group_modes()，将扁平模式列表重构为三级树状索引 (格式 -> 分辨率 -> 帧率列表)，
   以支撑 GUI 三级联动下拉框与硬件能力清单表格渲染。
"""

import re
import sys
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
    if sys.platform.startswith("win"):
        from camera.windows_backend import get_windows_camera_modes
        return get_windows_camera_modes(device)

    modes = _modes_from_ioctl(device)
    if modes is None:
        modes = _modes_from_v4l2ctl(device)
    return _finalize_modes(modes)


def fallback_modes():
    return tuple(
        CameraMode(fmt, w, h, fps) for fmt, w, h, fps in COMMON_FALLBACK_MODES
    )


def group_modes(modes):
    """
    将模式按 format -> (width, height) -> [fps, ...] 分组组织。
    MJPG 优先,分辨率和帧率均按降序排列。
    """
    grouped = {}
    for mode in modes:
        fmt = normalize_format(mode.pixel_format)
        res = (mode.width, mode.height)
        if fmt not in grouped:
            grouped[fmt] = {}
        if res not in grouped[fmt]:
            grouped[fmt][res] = []
        if mode.fps not in grouped[fmt][res]:
            grouped[fmt][res].append(mode.fps)

    for fmt, res_map in grouped.items():
        for res in res_map:
            res_map[res].sort(reverse=True)

    return grouped


def get_available_formats(modes):
    grouped = group_modes(modes)
    formats = list(grouped.keys())
    formats.sort(key=lambda x: (0 if x == "MJPG" else 1, x))
    return formats


def get_resolutions_for_format(modes, fmt):
    grouped = group_modes(modes)
    res_map = grouped.get(normalize_format(fmt), {})
    resolutions = list(res_map.keys())
    resolutions.sort(key=lambda r: (-(r[0] * r[1]), -r[0], -r[1]))
    return resolutions


def get_fps_for_resolution(modes, fmt, width, height):
    grouped = group_modes(modes)
    res_map = grouped.get(normalize_format(fmt), {})
    fps_list = list(res_map.get((width, height), []))
    fps_list.sort(reverse=True)
    return fps_list


def find_mode(modes, fmt, width, height, fps):
    """在 modes 中查找与格式、分辨率和帧率最匹配的 CameraMode。"""
    norm_fmt = normalize_format(fmt)
    candidates = [
        m for m in modes
        if normalize_format(m.pixel_format) == norm_fmt
        and m.width == width
        and m.height == height
    ]
    if not candidates:
        return None
    # 优先匹配最接近的目标 FPS
    return min(candidates, key=lambda m: abs(m.fps - fps))
