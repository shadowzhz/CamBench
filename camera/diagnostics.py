"""
运行时诊断。

"实测 FPS 跑不满标称值"的三个常见根因在这里给出线索:
1. USB 2.0 总线带宽不足以承载高分辨率高帧率模式;
2. 自动曝光在光线不足时把帧率压到环境光频率的倍数;
3. uvcvideo 驱动带宽协商失败留下的内核日志。
"""

import os
import re

from camera.utils import run_cmd


_USB_SPEED_LABELS = {
    "1.5": "USB 1.x Low-Speed (1.5 Mbps)",
    "12": "USB 1.x Full-Speed (12 Mbps)",
    "480": "USB 2.0 High-Speed (480 Mbps)",
    "5000": "USB 3.x SuperSpeed (5 Gbps)",
    "10000": "USB 3.x SuperSpeed+ (10 Gbps)",
}

# UVC 相机上控制自动曝光的 V4L2 控制名(新旧驱动命名不同)
_EXPOSURE_CONTROLS = (
    "auto_exposure",
    "exposure_auto",
)

# V4L2_CID_EXPOSURE_AUTO 的 UVC 取值:1=手动,3=光圈优先(自动)
_EXPOSURE_AUTO_VALUE = "3"

_EXPOSURE_MODE_LABELS = {
    "1": "手动",
    "3": "自动(光圈优先)",
}


def speed_label(value):
    if not value:
        return "未知"
    return _USB_SPEED_LABELS.get(value, f"{value} Mbps")


def usb_speed(device):
    """
    从 sysfs 读取设备所在 USB 端口的速度。

    返回 (速度字符串, 标签);非 USB 设备或读取失败返回 (None, None)。
    """
    node = os.path.basename(device)
    path = os.path.realpath(
        f"/sys/class/video4linux/{node}/device"
    )

    for _ in range(4):
        speed_path = os.path.join(path, "speed")
        if os.path.isfile(speed_path):
            try:
                with open(speed_path, "r", encoding="ascii") as f:
                    value = f.read().strip()
            except OSError:
                return None, None
            return value, speed_label(value)

        parent = os.path.dirname(path)
        if not parent or parent == path:
            break
        path = parent

    return None, None


def read_exposure_state(device):
    """
    读取自动曝光控制状态,返回 (控制名, 当前值字符串, 含义)。

    控制不存在、v4l2-ctl 不可用或读取失败时返回 None。
    """
    listing = run_cmd(
        ["v4l2-ctl", "-d", device, "--list-ctrls"]
    )

    name = None

    for candidate in _EXPOSURE_CONTROLS:
        if re.search(
            rf"^\s*{candidate}\s+0x",
            listing,
            re.MULTILINE,
        ):
            name = candidate
            break

    if name is None:
        return None

    value_text = run_cmd(
        ["v4l2-ctl", "-d", device, f"--get-ctrl={name}"]
    )

    match = re.search(
        rf"{name}\s*:\s*(-?\d+)",
        value_text,
    )

    if not match:
        return None

    value = match.group(1)

    return name, value, _EXPOSURE_MODE_LABELS.get(value, value)


def uvcvideo_bandwidth_warnings(log_text):
    """
    从内核日志中提取 uvcvideo 带宽/等时传输相关告警。
    纯函数,便于测试。
    """
    warnings = []

    for line in log_text.splitlines():
        if "uvcvideo" not in line:
            continue
        if not re.search(
            r"bandwidth|isochronous",
            line,
            re.IGNORECASE,
        ):
            continue
        warnings.append(line.strip())

    return warnings


def kernel_uvcvideo_warnings():
    """读取内核日志并提取 uvcvideo 告警;dmesg 被限制时回退 journalctl。"""
    text = run_cmd(["dmesg"])

    if not text.strip():
        text = run_cmd(
            ["journalctl", "-k", "--no-pager"]
        )

    return uvcvideo_bandwidth_warnings(text)


def diagnose_camera(camera, mode=None):
    """生成针对指定相机(和可选模式)的诊断报告文本。"""
    lines = [
        f"设备: {camera.device}   ({camera.name})"
    ]

    speed_value, speed_text = usb_speed(camera.device)

    if speed_text is None:
        lines.append("USB 速度: 未知(非 USB 设备或 sysfs 不可用)")
    else:
        lines.append(f"USB 速度: {speed_text}")
        if (
            speed_value == "480"
            and mode is not None
            and mode.fps >= 60
        ):
            lines.append(
                "提示: USB 2.0 总线(480 Mbps)对高帧率模式带宽紧张,"
                "建议换用 USB 3.0 口、降低分辨率或帧率。"
            )

    exposure = read_exposure_state(camera.device)

    if exposure is None:
        lines.append(
            "曝光: 无法读取(需要 v4l2-ctl,或相机未提供曝光控制)"
        )
    else:
        name, value, meaning = exposure
        lines.append(f"曝光: {name}={value} ({meaning})")
        if value == _EXPOSURE_AUTO_VALUE:
            lines.append(
                "提示: 当前为自动曝光,光线不足时相机可能自行压低帧率。可尝试切换手动曝光:"
            )
            lines.append(
                f"  v4l2-ctl -d {camera.device} --set-ctrl={name}=1"
            )

    warnings = kernel_uvcvideo_warnings()

    if warnings:
        lines.append(
            f"内核 uvcvideo 带宽告警: {len(warnings)} 条,最近 3 条:"
        )
        lines.extend(f"  {w}" for w in warnings[-3:])
    else:
        lines.append("内核 uvcvideo 带宽告警: 未发现")

    return "\n".join(lines)
