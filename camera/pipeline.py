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
    fmt = normalize_format(mode.pixel_format)
    if fmt == "MJPG":
        return f"image/jpeg,width={mode.width},height={mode.height},framerate={fps_num}/{fps_den}"
    if fmt in ("YUY2", "YUYV"):
        return f"video/x-raw,format=YUY2,width={mode.width},height={mode.height},framerate={fps_num}/{fps_den}"
    return f"video/x-raw,width={mode.width},height={mode.height},framerate={fps_num}/{fps_den}"


def _jpeg_decoder():
    """Prefer an installed accelerated JPEG decoder for high-FPS MJPG cameras."""
    for name in ("v4l2sljpegdec", "nvjpegdec", "vaapijpegdec"):
        if Gst.ElementFactory.find(name) is not None:
            return name
    return "jpegdec"


def has_accelerated_jpeg_decoder():
    return _jpeg_decoder() != "jpegdec"


def build_gstreamer_pipeline(device, mode, use_io_mode=True):
    fmt = normalize_format(mode.pixel_format)
    decoder = _jpeg_decoder() if fmt == "MJPG" else None

    if decoder:
        print(f"GStreamer decoder={decoder}")

    decoder_chain = f"jpegparse ! {decoder} ! " if decoder else ""
    return (
        f"{_build_source(device, use_io_mode)}! "
        f"{_build_caps(mode)} ! "
        f"{decoder_chain}"
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


def build_counter_pipeline(device, mode, use_io_mode=True):
    """Count buffers directly from v4l2src, without JPEG decode/conversion."""
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
