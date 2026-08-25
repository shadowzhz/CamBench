import gi

gi.require_version("Gst", "1.0")

from gi.repository import Gst

from camera.utils import normalize_format
from camera.modes import fps_fraction


def _build_source(device, use_io_mode=True):
    source = f"v4l2src device={device} do-timestamp=true "
    if use_io_mode:
        source += "io-mode=2 "
    return source


def _build_caps(mode):
    fps_num, fps_den = fps_fraction(mode.fps)

    if normalize_format(mode.pixel_format) == "MJPG":
        return (
            f"image/jpeg,width={mode.width},height={mode.height},"
            f"framerate={fps_num}/{fps_den}"
        )

    return (
        f"video/x-raw,format=YUY2,width={mode.width},"
        f"height={mode.height},framerate={fps_num}/{fps_den}"
    )


def build_gstreamer_pipeline(device, mode, use_io_mode=True):
    return (
        f"{_build_source(device, use_io_mode)}! "
        f"{_build_caps(mode)} ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


def build_counter_pipeline(device, mode, use_io_mode=True):
    return (
        f"{_build_source(device, use_io_mode)}! "
        f"{_build_caps(mode)} ! "
        "fakesink name=sink sync=false"
    )


def close_counter_pipeline(pipeline, pad=None, probe_id=None):
    try:
        if pad and probe_id:
            pad.remove_probe(probe_id)
    except Exception:
        pass

    try:
        if pipeline:
            pipeline.set_state(Gst.State.NULL)
    except Exception:
        pass
