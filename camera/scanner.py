import glob
import shutil

from core.logger import log

from camera.models import CameraInfo
from camera.modes import (
    get_camera_modes,
    fallback_modes,
)

from camera.utils import (
    device_sort_key,
    run_cmd,
    parse_field,
    is_video_capture_node,
)



def scan_cameras():

    devices = sorted(
        glob.glob("/dev/video*"),
        key=device_sort_key
    )


    if not devices:

        log(
            "scan: no /dev/video devices"
        )

        return []


    cameras=[]

    physical_indexes={}

    has_v4l2_ctl = (
        shutil.which(
            "v4l2-ctl"
        )
        is not None
    )


    for device in devices:


        if not has_v4l2_ctl:

            cameras.append(
                CameraInfo(
                    device=device,
                    name=device,
                    bus_info="",
                    modes=fallback_modes()
                )
            )

            continue



        info_text = run_cmd(
            [
                "v4l2-ctl",
                "-D",
                "-d",
                device
            ]
        )


        if info_text and not is_video_capture_node(info_text):

            log(
                f"scan: skip {device}"
            )

            continue



        modes=get_camera_modes(
            device
        )


        if not modes:

            log(
                f"scan: {device} no modes"
            )

            continue



        name=parse_field(
            info_text,
            "Card type",
            device
        )


        bus=parse_field(
            info_text,
            "Bus info",
            ""
        )


        identity=(
            name,
            bus
        ) if bus else (
            device,
        )



        if identity in physical_indexes:

            index=physical_indexes[identity]

            old=cameras[index]


            cameras[index]=CameraInfo(
                device=old.device,
                name=old.name,
                bus_info=old.bus_info,
                modes=old.modes,
                alt_devices=
                    old.alt_devices
                    +
                    (device,)
            )


            continue



        physical_indexes[identity]=len(cameras)


        cameras.append(
            CameraInfo(
                device=device,
                name=name,
                bus_info=bus,
                modes=modes
            )
        )


        log(
            f"scan: accepted {device}"
        )



    return cameras
