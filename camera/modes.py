import re
from fractions import Fraction

from core.config import (
    SUPPORTED_FORMATS,
    COMMON_FALLBACK_MODES,
)

from camera.models import CameraMode
from camera.utils import normalize_format, run_cmd



def fps_fraction(fps):

    if abs(
        fps-round(fps)
    ) < 0.01:

        return int(round(fps)), 1


    for value, numerator in (
        (23.976,24000),
        (29.97,30000),
        (59.94,60000),
        (119.88,120000),
    ):

        if abs(
            fps-value
        ) < 0.02:

            return numerator,1001


    fraction = Fraction(
        fps
    ).limit_denominator(1001)


    return (
        fraction.numerator,
        fraction.denominator
    )



def get_camera_modes(device):

    text = run_cmd(
        [
            "v4l2-ctl",
            "-d",
            device,
            "--list-formats-ext"
        ]
    )


    modes=[]

    current_format=None
    width=None
    height=None


    format_pattern=re.compile(
        r"\[\d+\]:\s*'([^']+)'"
    )

    size_pattern=re.compile(
        r"Size:\s*Discrete\s+(\d+)x(\d+)"
    )

    fps_pattern=re.compile(
        r"\(([\d.]+)\s+fps\)"
    )


    for raw in text.splitlines():

        line=raw.strip()


        m=format_pattern.search(line)

        if m:

            current_format=m.group(1).upper()

            continue


        m=size_pattern.search(line)

        if m:

            width=int(m.group(1))
            height=int(m.group(2))

            continue


        m=fps_pattern.search(line)

        if not m:
            continue


        if current_format not in SUPPORTED_FORMATS:
            continue


        if width is None:
            continue


        modes.append(
            CameraMode(
                current_format,
                width,
                height,
                float(m.group(1))
            )
        )


    unique={}


    for mode in modes:

        key=(
            normalize_format(mode.pixel_format),
            mode.width,
            mode.height,
            round(mode.fps,3)
        )

        unique[key]=mode


    result=list(unique.values())


    result.sort(
        key=lambda x:
        (
            0 if normalize_format(x.pixel_format)=="MJPG" else 1,
            -x.width*x.height,
            -x.fps
        )
    )


    return tuple(result)



def fallback_modes():

    return tuple(
        CameraMode(
            fmt,
            w,
            h,
            fps
        )
        for fmt,w,h,fps
        in COMMON_FALLBACK_MODES
    )
