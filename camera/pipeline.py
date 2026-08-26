import gi

gi.require_version("Gst", "1.0")

from gi.repository import Gst

from camera.utils import normalize_format
from camera.modes import fps_fraction


def _build_source(device, use_io_mode=True):
    # Let v4l2src negotiate the safest transport mode for the camera/driver.
    return f"v4l2src device={device} do-timestamp=true"


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


def _jpeg_decoders():
    """Return JPEG decoders in performance-first order."""
    return tuple(
        name
        for name in (
            "nvv4l2decoder",
            "v4l2sljpegdec",
            "nvjpegdec",
            "vaapijpegdec",
            "jpegdec",
            "avdec_mjpeg",
        )
        if Gst.ElementFactory.find(name) is not None
    )


def _jpeg_decoder():
    decoders = _jpeg_decoders()
    return decoders[0] if decoders else None


def has_accelerated_jpeg_decoder():
    decoder = _jpeg_decoder()
    return decoder not in (None, "jpegdec", "avdec_mjpeg")


def _jpeg_decoder_chain(decoder, output_format="BGR"):
    """Build a decoder chain with an explicit, predictable system-memory format."""
    if decoder == "nvv4l2decoder":
        # Jetson path validated by the Graduation project for 200 FPS MJPG.
        return (
            "queue max-size-buffers=4 leaky=downstream ! jpegparse ! "
            "nvv4l2decoder mjpeg=1 ! nvvidconv ! "
            f"video/x-raw,format={output_format} ! "
        )
    return (
        f"queue max-size-buffers=4 leaky=downstream ! jpegparse ! {decoder} ! "
        "videoconvert ! "
        f"video/x-raw,format={output_format} ! "
    )


def build_gstreamer_pipeline(device, mode, use_io_mode=True):
    """Build the compatibility OpenCV-GStreamer pipeline.

    High-FPS native capture uses the same decoder/caps chain, but reads the
    appsink directly through Gst instead of OpenCV's GStreamer wrapper.
    """
    fmt = normalize_format(mode.pixel_format)
    decoder = _jpeg_decoder() if fmt == "MJPG" else None

    if fmt == "MJPG":
        if decoder is None:
            raise RuntimeError("GStreamer JPEG decoder is unavailable")
        print(f"GStreamer decoder={decoder}")
        decoder_chain = _jpeg_decoder_chain(decoder, "BGR")
    else:
        decoder_chain = ""

    return (
        f"{_build_source(device, use_io_mode)} ! "
        f"{_build_caps(mode)} ! "
        f"{decoder_chain}"
        "queue max-size-buffers=2 leaky=downstream ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


def build_native_gstreamer_pipeline(device, mode):
    """Build the native Gst/appsink pipeline for high-FPS MJPG capture."""
    fmt = normalize_format(mode.pixel_format)
    if fmt != "MJPG":
        raise ValueError("native high-FPS GStreamer capture currently requires MJPG")

    decoder = _jpeg_decoder()
    if decoder is None:
        raise RuntimeError("GStreamer JPEG decoder is unavailable")

    print(f"GStreamer native decoder={decoder}")
    return (
        f"{_build_source(device)} ! "
        f"{_build_caps(mode)} ! "
        f"{_jpeg_decoder_chain(decoder, 'BGRx')}"
        "queue max-size-buffers=2 leaky=downstream ! "
        "appsink name=cambenchsink drop=true max-buffers=1 sync=false"
    )


def build_counter_pipeline(device, mode, use_io_mode=True):
    """Count buffers directly from v4l2src, without JPEG decode/conversion."""
    return (
        f"{_build_source(device, use_io_mode)} ! "
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
