"""Windows 平台摄像头后端:设备扫描、模式列表与硬件诊断。"""

import json
import shutil
import subprocess
import sys
from typing import List, Tuple

import cv2

from camera.models import CameraInfo, CameraMode
from camera.utils import run_cmd
from core import log

# Windows 下常见候选分辨率与帧率矩阵
_WINDOWS_DEFAULT_RESOLUTIONS = (
    (3840, 2160),
    (2560, 1440),
    (1920, 1080),
    (1280, 720),
    (640, 480),
    (320, 240),
)

_WINDOWS_DEFAULT_FPS = (120.0, 60.0, 30.0, 15.0)

_WINDOWS_DEFAULT_FORMATS = ("MJPG", "YUY2")


def get_windows_camera_modes(device: str = "0") -> Tuple[CameraMode, ...]:
    """为 Windows 设备提供标准候选模式列表(按像素数、帧率降序)。"""
    modes = []
    # MJPG 优先
    for fmt in _WINDOWS_DEFAULT_FORMATS:
        for w, h in _WINDOWS_DEFAULT_RESOLUTIONS:
            for fps in _WINDOWS_DEFAULT_FPS:
                modes.append(CameraMode(pixel_format=fmt, width=w, height=h, fps=fps))
    return tuple(modes)


def probe_resolutions_from_capture(cap) -> List[Tuple[int, int]]:
    """
    在已打开的 VideoCapture (DirectShow / MSMF) 上探测驱动实际支持的离散分辨率。

    【工作原理】
    Windows DirectShow 驱动在接收到 set(CAP_PROP_FRAME_WIDTH, w) 时，
    若请求的分辨率不受硬件支持，驱动会自动将其就近强行对齐(Clamp)到最近的硬件合法分辨率。
    随后调用 get() 读取回来的尺寸即为摄像头真实支持的离散分辨率。
    遍历通用标准候选分辨率，即可快速嗅探出该摄像头硬件暴露的所有真实分辨率。
    """
    try:
        found = set()
        for w, h in _WINDOWS_DEFAULT_RESOLUTIONS:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            act_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            act_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if act_w > 0 and act_h > 0:
                found.add((act_w, act_h))
        if found:
            return sorted(list(found), key=lambda r: (-(r[0] * r[1]), -r[0], -r[1]))
    except Exception:
        pass
    return list(_WINDOWS_DEFAULT_RESOLUTIONS)


def build_modes_for_resolutions(resolutions: List[Tuple[int, int]]) -> Tuple[CameraMode, ...]:
    """根据探测到的分辨率列表构建候选模式。"""
    modes = []
    for fmt in _WINDOWS_DEFAULT_FORMATS:
        for w, h in resolutions:
            for fps in _WINDOWS_DEFAULT_FPS:
                modes.append(CameraMode(pixel_format=fmt, width=w, height=h, fps=fps))
    return tuple(modes)


def get_windows_camera_names() -> List[str]:
    """
    通过 PowerShell WMI/CIM 获取 Windows 当前连接的摄像头友好名称列表。
    
    OpenCV 在 Windows 下只暴露整数索引 (0, 1, ...)，通过查询 Win32_PnPEntity
    中 PNPClass 为 'Camera' 或 'Image' 的物理设备名称，可以将其与 OpenCV 索引做友好关联。
    """
    if shutil.which("powershell") is None:
        return []

    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "$cams = @(Get-CimInstance Win32_PnPEntity | "
            "Where-Object { $_.PNPClass -in @('Camera', 'Image') -and $_.Status -eq 'OK' } | "
            "Select-Object -ExpandProperty Name); "
            "$cams | ConvertTo-Json"
        ),
    ]
    output = run_cmd(cmd, timeout=4)
    if not output:
        return []

    try:
        data = json.loads(output.strip())
        if isinstance(data, list):
            return [str(x) for x in data if x]
        if isinstance(data, str) and data:
            return [data]
    except Exception:
        # 非 JSON 单行文本回退
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines

    return []


def scan_windows_cameras(max_devices: int = 6) -> List[CameraInfo]:
    """
    在 Windows 下枚举有效摄像头索引,并关联友好名称。
    """
    friendly_names = get_windows_camera_names()
    cameras = []

    for index in range(max_devices):
        # 尝试使用 CAP_DSHOW 打开设备以确认物理存在
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        opened = cap.isOpened()
        if not opened:
            # 尝试 CAP_MSMF
            cap.release()
            cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
            opened = cap.isOpened()

        if not opened:
            cap.release()
            # 连续 2 个索引无法打开且已找到过设备,提早退出
            if index > 0 and len(cameras) >= 1:
                break
            continue

        probed_resolutions = probe_resolutions_from_capture(cap)
        cap.release()
        device_str = str(index)
        if index < len(friendly_names):
            name = friendly_names[index]
        else:
            name = f"Camera {index}"

        modes = build_modes_for_resolutions(probed_resolutions)
        cam_info = CameraInfo(
            device=device_str,
            name=name,
            bus_info=f"DirectShow/MSMF Device #{index}",
            modes=modes,
        )
        cameras.append(cam_info)
        log(f"scan: accepted Windows device {device_str} ({name})")

    return cameras


def diagnose_windows_camera(camera: CameraInfo, mode: CameraMode = None) -> str:
    """生成 Windows 平台的相机诊断报告。"""
    lines = [
        "=== Windows 摄像头诊断报告 ===",
        f"目标相机: {camera.name} (设备号: {camera.device})",
    ]
    if mode is not None:
        lines.append(f"请求模式: {mode.display_name}")

    lines.append("")
    lines.append("[1. 曝光与跑不满帧率说明]")
    lines.append(
        "  - 自动曝光(Auto Exposure)与低光补偿: 在光线不足时,UVC 相机固件会自动延长快门时间,\n"
        "    导致实测 FPS 强制降至 15~30 FPS。\n"
        "  - 建议: 打开 Windows 自带的「相机」应用 -> 设置,检查是否开启了低光补偿；\n"
        "    或使用相机厂商配置工具将曝光切换为「手动曝光」并提高环境照度。"
    )

    lines.append("")
    lines.append("[2. USB 总线带宽建议]")
    lines.append(
        "  - 高分辨率/高帧率(如 1080P@60FPS, 4K)推荐优先使用 MJPG 格式。\n"
        "  - YUY2(未压缩 YUV422)数据量巨大(1080P@60 约需 2 Gbps),在 USB 2.0(上限 480 Mbps)下无法跑满。\n"
        "  - 建议将相机插在主机后置的蓝色 USB 3.0/3.1 接口,避免经过低速 USB Hub。"
    )

    # 尝试获取 USB 控制器信息
    lines.append("")
    lines.append("[3. 本机 USB 主机控制器]")
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_USBController | Select-Object -ExpandProperty Name",
    ]
    usb_output = run_cmd(cmd, timeout=3)
    if usb_output:
        ctrls = [c.strip() for c in usb_output.splitlines() if c.strip()]
        for c in ctrls:
            lines.append(f"  - {c}")
    else:
        lines.append("  (无法通过 PowerShell 查询 USB 控制器列表)")

    return "\n".join(lines)
