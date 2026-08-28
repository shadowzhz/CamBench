import glob
import shutil

from camera import v4l2_io
from camera.models import CameraInfo
from camera.modes import get_camera_modes, fallback_modes
from camera.utils import (
    device_sort_key,
    is_video_capture_node,
    parse_field,
    run_cmd,
)
from core import log


def scan_cameras():
    """
    扫描 /dev/video*,返回物理摄像头列表。

    - 用 v4l2-ctl(优先)或 ioctl 过滤掉元数据等非采集节点;
    - 同一物理摄像头(card+bus 相同)的多个节点合并到一条记录。
    """
    devices = sorted(glob.glob("/dev/video*"), key=device_sort_key)
    if not devices:
        log("scan: no /dev/video devices")
        return []

    has_v4l2_ctl = shutil.which("v4l2-ctl") is not None
    cameras = []
    physical_indexes = {}

    for device in devices:
        if has_v4l2_ctl:
            info_text = run_cmd(["v4l2-ctl", "-D", "-d", device])
            if info_text and not is_video_capture_node(info_text):
                log(f"scan: skip {device}")
                continue
        else:
            # 无 v4l2-ctl 时用 ioctl 判定采集节点,并直接取设备名/总线信息
            capability = v4l2_io.query_capability(device)
            if capability is None or not capability.is_capture():
                log(f"scan: skip {device}")
                continue

        modes = get_camera_modes(device)
        if not modes:
            # 无 v4l2-ctl 时设备已被 ioctl 确认是采集节点;
            # 个别驱动不支持 ENUM_FRAMEINTERVALS,这里用预置模式兜底
            if not has_v4l2_ctl:
                modes = fallback_modes()
                log(f"scan: {device} using fallback modes")
            else:
                log(f"scan: {device} no modes")
                continue

        if has_v4l2_ctl:
            name = parse_field(info_text, "Card type", device)
            bus = parse_field(info_text, "Bus info", "")
        else:
            name = capability.card or device
            bus = capability.bus_info

        identity = (name, bus) if bus else (device,)
        if identity in physical_indexes:
            index = physical_indexes[identity]
            old = cameras[index]
            cameras[index] = CameraInfo(
                device=old.device,
                name=old.name,
                bus_info=old.bus_info,
                modes=old.modes,
                alt_devices=old.alt_devices + (device,),
            )
            continue

        physical_indexes[identity] = len(cameras)
        cameras.append(
            CameraInfo(device=device, name=name, bus_info=bus, modes=modes)
        )
        log(f"scan: accepted {device}")

    return cameras
