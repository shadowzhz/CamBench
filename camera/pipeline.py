import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from camera.utils import normalize_format
from camera.modes import fps_fraction


def _build_source(device, use_io_mode=True):
    # Graduation 的已验证 Jetson 高帧率路径使用 io-mode=2 (mmap)。
    io_mode = " io-mode=2" if use_io_mode else ""
    return f"v4l2src device={device}{io_mode} do-timestamp=true"


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
        return "nvv4l2decoder mjpeg=1 ! nvvidconv ! video/x-raw,format=" + output_format + " ! "
    return f"jpegparse ! {decoder} ! videoconvert ! video/x-raw,format={output_format} ! "


def _jetson_mjpeg_chain(output_format="BGRx"):
    # 不依赖 ElementFactory.find() 决定是否使用硬件解码；
    # Graduation 已验证的管道应直接交给 GStreamer 解析器，由实际环境决定可用性。
    return "nvv4l2decoder mjpeg=1 ! nvvidconv ! video/x-raw,format=" + output_format + " ! "


def build_gstreamer_pipeline(device, mode, use_io_mode=True):
    fmt = normalize_format(mode.pixel_format)
    decoder_chain = ""
    if fmt == "MJPG":
        decoder = "nvv4l2decoder" if _jetson_mjpeg_available() else _jpeg_decoder()
        if decoder is None:
            raise RuntimeError("GStreamer JPEG decoder is unavailable")
        print(f"GStreamer decoder={decoder}")
        decoder_chain = _jpeg_decoder_chain(decoder, "BGR")
    return f"{_build_source(device, use_io_mode)} ! {_build_caps(mode)} ! {decoder_chain}appsink drop=true max-buffers=1 sync=false"


def build_native_gstreamer_pipeline(device, mode):
    if normalize_format(mode.pixel_format) != "MJPG":
        raise ValueError("native high-FPS GStreamer capture currently requires MJPG")
    # 与 Graduation 的已验证管线保持一致：不要额外插入 jpegparse/queue，
    # 并明确使用 io-mode=2 + nvv4l2decoder + nvvidconv。
    return (
        f"v4l2src device={device} io-mode=2 do-timestamp=true ! "
        f"{_build_caps(mode)} ! "
        "nvv4l2decoder mjpeg=1 ! "
        "nvvidconv ! video/x-raw,format=BGRx ! "
        "queue max-size-buffers=1 leaky=downstream ! "
        "appsink name=cambenchsink drop=true max-buffers=1 sync=false"
    )


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
