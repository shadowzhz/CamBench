from gi.repository import Gst

from camera.utils import normalize_format
from camera.modes import fps_fraction



def build_gstreamer_pipeline(
    device,
    mode,
    use_io_mode=True
):

    fps_num,fps_den=fps_fraction(
        mode.fps
    )


    source=(
        f"v4l2src "
        f"device={device} "
        f"do-timestamp=true "
    )


    if use_io_mode:
        source += "io-mode=2 "



    if normalize_format(
        mode.pixel_format
    )=="MJPG":


        caps=(
            f"image/jpeg,"
            f"width={mode.width},"
            f"height={mode.height},"
            f"framerate={fps_num}/{fps_den}"
        )


        return (
            f"{source}! "
            f"{caps} ! "
            "jpegdec ! "
            "videoconvert ! "
            "video/x-raw,format=BGR ! "
            "appsink drop=true "
            "max-buffers=1 "
            "sync=false"
        )



    caps=(
        f"video/x-raw,"
        f"format=YUY2,"
        f"width={mode.width},"
        f"height={mode.height},"
        f"framerate={fps_num}/{fps_den}"
    )


    return (
        f"{source}! "
        f"{caps} ! "
        "videoconvert ! "
        "video/x-raw,format=BGR ! "
        "appsink drop=true "
        "max-buffers=1 "
        "sync=false"
    )




def build_counter_pipeline(
    device,
    mode,
    use_io_mode=True
):

    fps_num,fps_den=fps_fraction(
        mode.fps
    )


    source=(
        f"v4l2src "
        f"device={device} "
        f"do-timestamp=true "
    )


    if use_io_mode:
        source+="io-mode=2 "



    if normalize_format(
        mode.pixel_format
    )=="MJPG":

        caps=(
            f"image/jpeg,"
            f"width={mode.width},"
            f"height={mode.height},"
            f"framerate={fps_num}/{fps_den}"
        )


    else:

        caps=(
            f"video/x-raw,"
            f"format=YUY2,"
            f"width={mode.width},"
            f"height={mode.height},"
            f"framerate={fps_num}/{fps_den}"
        )


    return (
        f"{source}! "
        f"{caps} ! "
        "fakesink name=sink sync=false"
    )




def close_counter_pipeline(
    pipeline,
    pad=None,
    probe_id=None
):

    try:

        if pad and probe_id:

            pad.remove_probe(
                probe_id
            )

    except Exception:
        pass



    try:

        if pipeline:

            pipeline.set_state(
                Gst.State.NULL
            )

    except Exception:
        pass
    