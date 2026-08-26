import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from camera.utils import normalize_format
from camera.modes import fps_fraction


def _build_source(device, use_io_mode=True, name=None):
    io_mode = " io-mode=2" if use_io_mode else ""
    source_name = f" name={name}" if name else ""
    return f"v4l2src device={device}{io_mode}{source_name}"


def _build_caps(mode):
    fps_num, fps_den = fps_fraction(mode.fps)
    fmt = normalize_format(mode.pixel_format)
    if fmt == "MJPG":
        return f"image/jpeg,width={mode.width},height={mode.height},framerate={fps_num}/{fps_den}"
    if fmt in ("YUY2", "YUYV"):
        return f"video/x-raw,format=YUY2,width={mode.width},height={mode.height},framerate={fps_num}/{fps_den}"
    return f"video/x-raw,width={mode.width},height={mode.height},framerate={fps_num}/{fps_den}"


def _element_available(name):
    return Gst.ElementFactory.find(name) is not None


def _jetson_mjpeg_available():
    return _element_available("nvv4l2decoder") and _element_available("nvvidconv")


def _jpeg_decoders():
    return tuple(name for name in ("v4l2sljpegdec", "nvjpegdec", "vaapijpegdec", "jpegdec", "avdec_mjpeg") if _element_available(name))


def _jpeg_decoder():
    decoders = _jpeg_decoders()
    return decoders[0] if decoders else None


def has_accelerated_jpeg_decoder():
    return _jetson_mjpeg_available() or _jpeg_decoder() not in (None, "jpegdec", "avdec_mjpeg")


def _jpeg_decoder_chain(decoder, output_format="BGR"):
    if decoder == "nvv4l2decoder":
        return "queue max-size-buffers=4 leaky=downstream ! jpegparse ! nvv4l2decoder mjpeg=1 ! nvvidconv ! video/x-raw,format=" + output_format + " ! "
    return f"queue max-size-buffers=4 leaky=downstream ! {decoder} ! videoconvert ! video/x-raw,format={output_format} ! "


def _jetson_mjpeg_chain(output_format="BGRx"):
    if not _jetson_mjpeg_available():
        raise RuntimeError("Jetson nvv4l2decoder/nvvidconv is unavailable")
    return "jpegparse ! nvv4l2decoder mjpeg=1 ! nvvidconv ! video/x-raw,format=" + output_format + " ! "


def build_gstreamer_pipeline(device, mode, use_io_mode=True):
    fmt = normalize_format(mode.pixel_format)
    decoder_chain = ""
    if fmt == "MJPG":
        decoder = "nvv4l2decoder" if _jetson_mjpeg_available() else _jpeg_decoder()
        if decoder is None:
            raise RuntimeError("GStreamer JPEG decoder is unavailable")
        print(f"GStreamer decoder={decoder}")
        decoder_chain = _jpeg_decoder_chain(decoder, "BGR")
    return f"{_build_source(device, use_io_mode)} ! {_build_caps(mode)} ! {decoder_chain}queue max-size-buffers=2 leaky=downstream ! appsink drop=true max-buffers=1 sync=false"


def build_native_gstreamer_pipeline(device, mode):
    if normalize_format(mode.pixel_format) != "MJPG":
        raise ValueError("native high-FPS GStreamer capture currently requires MJPG")
    return f"{_build_source(device, True)} ! {_build_caps(mode)} ! {_jetson_mjpeg_chain('BGRx')}queue max-size-buffers=2 leaky=downstream ! appsink name=cambenchsink drop=true max-buffers=1 sync=false"


def build_high_fps_preview_pipeline(device, mode):
    """Native appsink path using the same software topology as Graduation."""
    if normalize_format(mode.pixel_format) != "MJPG":
        raise ValueError("high-FPS preview pipeline currently requires MJPG")
    decoder = "nvv4l2decoder" if _jetson_mjpeg_available() else _jpeg_decoder()
    if decoder is None:
        raise RuntimeError("GStreamer JPEG decoder is unavailable")
    print(f"GStreamer decoder={decoder}")
    if decoder == "nvv4l2decoder":
        pipeline = (
            f"{_build_source(device, True, 'cambenchsrc')} ! {_build_caps(mode)} ! "
            "jpegparse ! nvv4l2decoder mjpeg=1 ! nvvidconv ! "
            "video/x-raw,format=BGRx ! "
        )
    else:
        # Match Graduation's proven software fallback: no jpegparse and BGR
        # output directly from videoconvert.
        pipeline = (
            f"{_build_source(device, True, 'cambenchsrc')} ! {_build_caps(mode)} ! "
            f"{decoder} ! videoconvert ! video/x-raw,format=BGR ! "
        )
    return pipeline + "appsink name=cambenchsink drop=true max-buffers=1 sync=false"


def build_counter_pipeline(device, mode, use_io_mode=True):
    return f"{_build_source(device, use_io_mode)} ! {_build_caps(mode)} ! fakesink name=sink sync=false"


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
