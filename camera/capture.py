import time

import cv2

from core.logger import log

from camera.pipeline import (
    build_gstreamer_pipeline
)

from camera.utils import normalize_format



def read_first_frame(
    cap,
    attempts=30,
    stop_event=None
):

    for _ in range(attempts):

        if stop_event and stop_event.is_set():

            return None


        ok,frame=cap.read()


        if ok and frame is not None:

            return frame


        time.sleep(
            0.03
        )


    return None




def open_gstreamer_capture(
    camera,
    mode,
    errors,
    stop_event=None
):


    for device in camera.device_candidates:

        for io in (
            True,
            False
        ):


            if stop_event and stop_event.is_set():

                return None,"",None,""



            pipeline=build_gstreamer_pipeline(
                device,
                mode,
                io
            )


            cap=cv2.VideoCapture(
                pipeline,
                cv2.CAP_GSTREAMER
            )


            label=f"GStreamer {device}"



            if not cap.isOpened():

                errors.append(
                    f"{label}: open failed"
                )

                continue



            frame=read_first_frame(
                cap,
                stop_event=stop_event
            )


            if frame is not None:

                return (
                    cap,
                    label,
                    frame,
                    device
                )



            cap.release()



    return None,"",None,""




def open_v4l2_capture(
    camera,
    mode,
    errors,
    stop_event=None
):

    for device in camera.device_candidates:


        cap=cv2.VideoCapture(
            device,
            cv2.CAP_V4L2
        )


        if not cap.isOpened():

            continue



        fourcc=(
            "MJPG"
            if normalize_format(
                mode.pixel_format
            )=="MJPG"
            else
            "YUYV"
        )


        cap.set(
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*fourcc)
        )


        cap.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            mode.width
        )

        cap.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            mode.height
        )

        cap.set(
            cv2.CAP_PROP_FPS,
            mode.fps
        )


        frame=read_first_frame(
            cap,
            stop_event=stop_event
        )


        if frame is not None:

            return (
                cap,
                f"OpenCV V4L2 {device}",
                frame,
                device
            )


        cap.release()



    return None,"",None,""




def open_capture(
    camera,
    mode,
    stop_event=None
):

    errors=[]


    result=open_gstreamer_capture(
        camera,
        mode,
        errors,
        stop_event
    )


    if result[0]:

        return (
            *result,
            errors
        )



    result=open_v4l2_capture(
        camera,
        mode,
        errors,
        stop_event
    )


    if result[0]:

        return (
            *result,
            errors
        )


    return (
        None,
        "",
        None,
        "",
        errors
    )
