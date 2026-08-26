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
        return (
            f"image/jpeg,width={mode.width},height={mode.height},"
            f"framerate={fps_num}/{fps_den}"
        )
    if fmt in ("YUY2", "YUYV"):
        return (
            f"video/x-raw,format=YUY2,width={mode.width},height={mode.height},"
            f"framerate={fps_num}/{fps_den}"
        )
    return (
        f"video/x-raw,width={mode.width},height={mode.height},"
        f"framerate={fps_num}/{fps_den}"
    )


def _jpeg_decoder():
    """Return an explicitly available JPEG decoder, or None for decodebin."""
    for name in (
        "v4l2sljpegdec",
        "nvjpegdec",
        "vaapijpegdec",
        "jpegdec",
        "avdec_mjpeg",
    ):
        if Gst.ElementFactory.find(name) is not None:
            return name
    return None


def has_accelerated_jpeg_decoder():
    return _jpeg_decoder() not in (None, "jpegdec", "avdec_mjpeg")


def build_gstreamer_pipeline(device, mode, use_io_mode=True):
    fmt = normalize_format(mode.pixel_format)
    decoder = _jpeg_decoder() if fmt == "MJPG" else None

    if fmt == "MJPG":
        if decoder:
            decoder_chain = f"jpegparse ! {decoder} ! "
            print(f"GStreamer decoder={decoder}")
        else:
            # decodebin lets GStreamer select any installed MJPEG/JPEG decoder
            # instead of failing during pipeline construction.
            decoder_chain = "jpegparse ! decodebin ! "
            print("GStreamer decoder=decodebin")
    else:
        decoder_chain = ""

    return (
        f"{_build_source(device, use_io_mode)}! "
        f"{_build_caps(mode)} ! "
        f"{decoder_chain}"
        "videoconvert ! video/x-raw,format=BGR ! "
        "queue max-size-buffers=2 leaky=downstream ! "
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
