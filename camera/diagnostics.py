"""
运行时诊断。

"实测 FPS 跑不满标称值"的三个常见根因在这里给出线索:
1. USB 2.0 总线带宽不足以承载高分辨率高帧率模式;
2. 自动曝光在光线不足时把帧率压到环境光频率的倍数;
3. uvcvideo 驱动带宽协商失败留下的内核日志。
"""

import os
import re
import sys

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
    if sys.platform.startswith("win"):
        from camera.windows_backend import diagnose_windows_camera
        return diagnose_windows_camera(camera, mode)

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

    # 检查是否开启了曝光动态降帧 (exposure_dynamic_framerate)
    dyn_fps_val = run_cmd(["v4l2-ctl", "-d", camera.device, "--get-ctrl=exposure_dynamic_framerate"])
    if "exposure_dynamic_framerate: 1" in dyn_fps_val:
        lines.append(
            "动态降帧: exposure_dynamic_framerate=1 (开启)\n"
            "提示: 固件在弱光下会主动降低帧率以加长曝光时间。关闭该选项可强制拉满帧率:\n"
            f"  v4l2-ctl -d {camera.device} --set-ctrl=exposure_dynamic_framerate=0"
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


def check_device_busy(device):
    """
    检查 Linux 视频设备节点是否被其他进程占用。
    返回占用该节点的 (pid, comm) 列表，或空列表。
    """
    if sys.platform.startswith("win"):
        return []

    dev_str = str(device)
    if not os.path.exists(dev_str):
        return []

    fuser_out = run_cmd(["fuser", dev_str])
    pids = re.findall(r"\b\d+\b", fuser_out)
    if not pids:
        lsof_out = run_cmd(["lsof", "-t", dev_str])
        pids = re.findall(r"\b\d+\b", lsof_out)

    busy_procs = []
    current_pid = str(os.getpid())
    for pid in sorted(set(pids), key=int):
        if pid == current_pid:
            continue
        comm = ""
        comm_path = f"/proc/{pid}/comm"
        if os.path.isfile(comm_path):
            try:
                with open(comm_path, "r", encoding="utf-8", errors="ignore") as f:
                    comm = f.read().strip()
            except OSError:
                pass
        busy_procs.append((pid, comm or "未知进程"))
    return busy_procs


def check_device_permission(device):
    """检查设备节点是否有读写权限。"""
    dev_str = str(device)
    if not os.path.exists(dev_str):
        return True
    return os.access(dev_str, os.R_OK | os.W_OK)


def diagnose_open_failure(camera, mode, raw_errors=None):
    """
    对摄像头开启失败进行深度原因诊断，生成人话版诊断报告与切实可行的解决建议。
    """
    if raw_errors is None:
        raw_errors = []
    elif isinstance(raw_errors, str):
        raw_errors = [raw_errors]
    raw_text = "\n".join(raw_errors)

    device = camera.device if camera else "/dev/video0"
    device_name = camera.name if camera else "未知摄像头"

    fmt = mode.pixel_format.upper() if mode else "未知"
    width = mode.width if mode else 0
    height = mode.height if mode else 0
    fps = mode.fps if mode else 0.0

    # 1. 检查权限
    if not sys.platform.startswith("win") and not check_device_permission(device):
        return (
            f"【无法访问设备】权限不足 (Permission Denied)\n\n"
            f"● 设备节点: {device} ({device_name})\n"
            f"● 具体原因: 当前系统用户没有读写该摄像头节点的权限。\n\n"
            f"【解决办法】\n"
            f"1. 永久授权: 在终端运行以下命令将当前用户加入 video 组，完成后注销重新登录:\n"
            f"   sudo usermod -a -G video $USER\n"
            f"2. 临时授权: 在终端运行:\n"
            f"   sudo chmod 666 {device}"
        )

    # 2. 检查被其他进程占用
    busy_procs = check_device_busy(device)
    if busy_procs or "Device or resource busy" in raw_text:
        proc_str = "、".join(f"{comm}(PID {pid})" for pid, comm in busy_procs) if busy_procs else "其他后台程序"
        return (
            f"【打开相机失败】设备正被其他软件占用\n\n"
            f"● 设备节点: {device} ({device_name})\n"
            f"● 占用进程: {proc_str}\n"
            f"● 具体原因: V4L2 视频采集设备节点属于独占资源，已被其他程序打开锁定。\n\n"
            f"【解决办法】\n"
            f"请关闭可能正在使用摄像头的软件后重试，例如:\n"
            f"• 网页浏览器 (Chrome / Edge / Firefox 中已开启摄像头的标签页)\n"
            f"• 通讯会议软件 (腾讯会议、微信视频、Zoom、Teams)\n"
            f"• 录播推流软件 (OBS Studio、Cheese、Kamoso 等)"
        )

    # 3. 检查 USB 2.0 带宽超限 (最核心且高发的场景，尤其是 YUY2/YUYV/未压缩高分辨率)
    is_uncompressed = fmt in ("YUY2", "YUYV", "UYVY", "NV12", "RGB", "BGR", "RGB3", "BGR3")
    bpp = 3.0 if fmt in ("RGB", "BGR", "RGB3", "BGR3") else 2.0
    frame_mb = (width * height * bpp) / (1024 * 1024) if (width and height) else 0.0
    bandwidth_mb_s = frame_mb * fps

    speed_value, speed_text = usb_speed(device) if not sys.platform.startswith("win") else (None, None)
    is_usb2 = (speed_value in ("480", "12", "1.5")) or (speed_value is None and is_uncompressed and width >= 1280)

    # 罗技摄像头判定 (例如 046d:0825 C270)
    is_logitech = "046d" in device_name.lower() or "logitech" in device_name.lower()

    # 内核告警
    warnings = kernel_uvcvideo_warnings() if not sys.platform.startswith("win") else []
    has_kernel_bandwidth_warning = any(
        re.search(r"bandwidth|altsetting|isochronous|cannot maintain|No space left", w, re.I)
        for w in warnings
        )

    if is_uncompressed and (bandwidth_mb_s >= 16.0 or (is_usb2 and width >= 1280) or has_kernel_bandwidth_warning):
        logitech_note = ""
        if is_logitech:
            logitech_note = (
                f"\n★ 特殊提示 (罗技固件缺陷): 该设备为罗技老款 UVC 摄像头，其固件存在已知缺陷，"
                f"无论设置多低帧率都会强行索要最大 USB 端点带宽(3072字节/微帧)，极易被系统内核拒绝。"
            )

        kernel_note = ""
        if warnings:
            kernel_note = f"\n● 内核日志告警: {warnings[-1]}"

        return (
            f"【打开相机失败】USB 物理总线带宽超限 (格式为未压缩 {fmt})\n\n"
            f"● 请求模式: {fmt} {width}x{height} @ {fps:g} FPS\n"
            f"● 数据吞吐量: 单帧约 {frame_mb:.2f} MB，每秒未压缩原始码流达 {bandwidth_mb_s:.1f} MB/s\n"
            f"● 接口环境: {speed_text or 'USB 2.0 (480 Mbps)'} (等时传输理论上限约 24 MB/s，实际可用仅 18~20 MB/s){logitech_note}{kernel_note}\n\n"
            f"【解决办法】\n"
            f"1. 【推荐】切换编码格式为【MJPG】: MJPG 经由摄像头内部硬件芯片压缩，数据量大幅缩减 80%~90%，可在 720P/1080P 下稳定流畅运行。\n"
            f"2. 降低分辨率: 若因算法必须使用未压缩 {fmt}，请将分辨率降低至 640x480 或以下。\n"
            f"3. 更换接口: 尝试将摄像头插入主板后置原生的 USB 3.0+ (蓝色/红色) 独立接口，避开机箱前置插口与拓展坞。"
        )

    # 4. 模式被驱动/底层拒绝
    if "模式被拒绝" in raw_text:
        return (
            f"【打开相机失败】硬件驱动拒绝了当前采集模式\n\n"
            f"● 请求参数: {fmt} {width}x{height} @ {fps:g} FPS\n"
            f"● 具体原因: 尽管设备描述符中列出了此模式，但在与驱动建立会话时，底层驱动未能成功锁定该分辨率/帧率组合。\n\n"
            f"【解决办法】\n"
            f"1. 尝试选择该格式下的标准分辨率（如 640x480、1280x720 等常规挡位）；\n"
            f"2. 切换编码格式为【MJPG】重试。"
        )

    # 5. 抓帧超时 / 无画面
    if "无画面" in raw_text:
        return (
            f"【打开相机失败】设备已打开但未输出有效画面 (抓帧超时)\n\n"
            f"● 设备节点: {device} ({device_name})\n"
            f"● 请求模式: {fmt} {width}x{height} @ {fps:g} FPS\n"
            f"● 具体原因: 底层接口已成功握手，但在超时时间（约2秒）内摄像头未送出任何图像数据帧。\n\n"
            f"【排查与解决】\n"
            f"1. 检查物理遮挡: 确认摄像头镜头盖或物理防窥拨片已完全打开；\n"
            f"2. 固件死锁重置: 快速连续切换采集模式可能导致部分摄像头内部 ISP 芯片死锁，请拔出 USB 重新插入；\n"
            f"3. 供电与虚拟机: 确保 USB 供电充足；若运行在虚拟机/容器内，请确认已分配 USB 3.0 控制器并正确直通。"
        )

    # 6. Windows 平台特有诊断提示
    if sys.platform.startswith("win"):
        return (
            f"【打开相机失败】无法初始化 Windows 采集通道\n\n"
            f"● 设备: {device_name}\n"
            f"● 模式: {fmt} {width}x{height} @ {fps:g} FPS\n\n"
            f"【排查与解决】\n"
            f"1. 检查系统相机隐私权限: 打开 Windows 设置 -> 隐私和安全性 -> 相机，确认“允许应用访问你的相机”已开启；\n"
            f"2. 检查是否有其他应用独占相机（如自带相机应用、微信、腾讯会议等）；\n"
            f"3. 尝试更换为 MJPG 格式或降低分辨率。\n\n"
            f"底层错误详情:\n{raw_text or '未知错误'}"
        )

    # 7. 兜底通用失败
    return (
        f"【打开相机失败】\n\n"
        f"● 设备节点: {device} ({device_name})\n"
        f"● 目标模式: {fmt} {width}x{height} @ {fps:g} FPS\n\n"
        f"底层错误详情:\n{raw_text or '未能成功建立视频流'}\n\n"
        f"【通用建议】\n"
        f"1. 推荐切换为兼容性最好的【MJPG】格式重试；\n"
        f"2. 点击主界面【🔍 诊断】按钮获取详细的硬件状态报告；\n"
        f"3. 尝试重新插拔 USB 摄像头以重置驱动状态。"
        )
