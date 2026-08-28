import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from camera.modes import fps_fraction
from camera.utils import normalize_format


def _build_source(device, use_io_mode=True, name=None):
    # io-mode=2 即 mmap:内核与用户空间共享缓冲区,省一次拷贝
    io_mode = " io-mode=2" if use_io_mode else ""
    source_name = f" name={name}" if name else ""
    return f"v4l2src device={device}{io_mode}{source_name}"


def _build_caps(mode):
    """把目标模式写成 GStreamer caps;framerate 必须显式给出,
    否则 v4l2src 自动协商时经常落在低帧率档位。"""
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
    """按优先级列出可用的 JPEG 解码器:硬件在前,软件兜底。"""
    return tuple(
        name
        for name in (
            "v4l2sljpegdec",
            "nvjpegdec",
            "vaapijpegdec",
            "jpegdec",
            "avdec_mjpeg",
        )
        if _element_available(name)
    )


def _jpeg_decoder():
    decoders = _jpeg_decoders()
    return decoders[0] if decoders else None


def has_accelerated_jpeg_decoder():
    """是否具备硬件 JPEG 解码能力(纯软件 jpegdec/avdec 不算)。"""
    return _jetson_mjpeg_available() or _jpeg_decoder() not in (None, "jpegdec", "avdec_mjpeg")


def _jpeg_decoder_chain(decoder, output_format="BGR"):
    if decoder == "nvv4l2decoder":
        return (
            "queue max-size-buffers=4 leaky=downstream ! jpegparse ! "
            "nvv4l2decoder mjpeg=1 ! nvvidconv ! "
            f"video/x-raw,format={output_format} ! "
        )
    return (
        f"queue max-size-buffers=4 leaky=downstream ! {decoder} ! "
        f"videoconvert ! video/x-raw,format={output_format} ! "
    )


def _jetson_mjpeg_chain(output_format="BGRx"):
    if not _jetson_mjpeg_available():
        raise RuntimeError("Jetson 的 nvv4l2decoder/nvvidconv 不可用")
    return f"jpegparse ! nvv4l2decoder mjpeg=1 ! nvvidconv ! video/x-raw,format={output_format} ! "


def build_gstreamer_pipeline(device, mode, use_io_mode=True):
    fmt = normalize_format(mode.pixel_format)
    decoder_chain = ""
    if fmt == "MJPG":
        decoder = "nvv4l2decoder" if _jetson_mjpeg_available() else _jpeg_decoder()
        if decoder is None:
            raise RuntimeError("找不到可用的 GStreamer JPEG 解码器")
        decoder_chain = _jpeg_decoder_chain(decoder, "BGR")
    return (
        f"{_build_source(device, use_io_mode)} ! {_build_caps(mode)} ! "
        f"{decoder_chain}"
        # 队列满时丢帧,预览永远拿最新画面,采集端不会被 GUI 卡顿反压;
        # appsink max-buffers=1 + drop + sync=false 是最低延迟的消费方式
        "queue max-size-buffers=2 leaky=downstream ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


def build_native_gstreamer_pipeline(device, mode):
    if normalize_format(mode.pixel_format) != "MJPG":
        raise ValueError("原生高帧率 GStreamer 采集仅支持 MJPG")
    return (
        f"{_build_source(device, True)} ! {_build_caps(mode)} ! "
        f"{_jetson_mjpeg_chain('BGRx')}queue max-size-buffers=2 leaky=downstream ! "
        "appsink name=cambenchsink drop=true max-buffers=1 sync=false"
    )


def build_high_fps_preview_pipeline(device, mode):
    """高帧率 MJPG 的原生 appsink 管线,源端命名为 cambenchsrc 供统计用。"""
    if normalize_format(mode.pixel_format) != "MJPG":
        raise ValueError("高帧率预览管线仅支持 MJPG")
    decoder = "nvv4l2decoder" if _jetson_mjpeg_available() else _jpeg_decoder()
    if decoder is None:
        raise RuntimeError("找不到可用的 GStreamer JPEG 解码器")

    if decoder == "nvv4l2decoder":
        pipeline = (
            f"{_build_source(device, True, 'cambenchsrc')} ! {_build_caps(mode)} ! "
            "jpegparse ! nvv4l2decoder mjpeg=1 ! nvvidconv ! video/x-raw,format=BGRx ! "
        )
    else:
        # 软件解码回退:不走 jpegparse,直接解码后由 videoconvert 转 BGR
        pipeline = (
            f"{_build_source(device, True, 'cambenchsrc')} ! {_build_caps(mode)} ! "
            f"{decoder} ! videoconvert ! video/x-raw,format=BGR ! "
        )
    return pipeline + "appsink name=cambenchsink drop=true max-buffers=1 sync=false"
