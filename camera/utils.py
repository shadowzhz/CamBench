import os
import re
import subprocess

from core import log


def normalize_format(pixel_format):
    """V4L2 的 YUYV 和 DirectShow 的 YUY2 是同一种格式,统一成 YUY2。"""
    if pixel_format in {"YUYV", "YUY2"}:
        return "YUY2"
    return pixel_format


def device_sort_key(path):
    if isinstance(path, int):
        return path
    str_path = str(path)
    if str_path.isdigit():
        return int(str_path)
    match = re.search(r"video(\d+)$", str_path)
    return int(match.group(1)) if match else 9999


def run_cmd(args, timeout=4):
    """执行外部命令。失败(命令不存在/超时)时记录日志并返回空字符串。"""
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        log(f"run_cmd: {args[0]} 未安装")
        return ""
    except subprocess.TimeoutExpired:
        log(f"run_cmd: {args[0]} 超时(>{timeout}s)")
        return ""
    return result.stdout


def parse_field(text, field_name, default=""):
    """从 v4l2-ctl 输出中取 "字段名: 值" 的值部分。"""
    match = re.search(rf"{re.escape(field_name)}\s*:\s*(.+)", text)
    return match.group(1).strip() if match else default


def parse_device_caps(text):
    """提取 v4l2-ctl -D 输出中 "Device Caps" 段的条目。"""
    caps = []
    active = False
    for line in text.splitlines():
        if re.search(r"Device Caps\s*:", line):
            active = True
            continue
        if not active:
            continue
        if not line.startswith((" ", "\t")):
            break
        item = line.strip()
        if item:
            caps.append(item)
    return caps


def is_video_capture_node(text):
    """判断 v4l2-ctl -D 输出是否为 Video Capture 节点。"""
    caps = parse_device_caps(text)
    if caps:
        return any(
            c in {"Video Capture", "Video Capture Multiplanar"} for c in caps
        )
    return bool(
        re.search(r"^\s*Video Capture(?: Multiplanar)?\s*$", text, re.MULTILINE)
    )


def camera_device_present(camera):
    import sys
    if sys.platform.startswith("win"):
        return True
    return any(os.path.exists(device) for device in camera.device_candidates)
