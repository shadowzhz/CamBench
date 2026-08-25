import time
from collections import deque
import threading

from workers.base import BaseWorker

from camera.pipeline import (
    build_counter_pipeline,
    close_counter_pipeline
)

from camera.utils import camera_device_present

from core.events import (
    make_stats_event,
    make_error_event,
    make_device_lost_event,
    make_stopped_event,
)

from core.config import STATS_ONLY_UPDATE_FPS

from core.logger import log

from gi.repository import Gst



class CounterWorker(BaseWorker):


    def __init__(
        self,
        camera,
        mode,
        event_queue
    ):

        super().__init__(
            event_queue
        )

        self.camera=camera
        self.mode=mode

        self.pipeline=None



    def stop(self):

        super().stop()

        if self.pipeline:

            self.pipeline.set_state(
                Gst.State.NULL
            )



    def run(self):

        pipeline_string=build_counter_pipeline(
            self.camera.device,
            self.mode
        )


        try:

            pipeline=Gst.parse_launch(
                pipeline_string
            )


        except Exception as e:

            self.event_queue.put(
                make_error_event(
                    str(e)
                )
            )

            return



        self.pipeline=pipeline



        sink=pipeline.get_by_name(
            "sink"
        )


        pad=sink.get_static_pad(
            "sink"
        )



        counter={

            "count":0,

            "times":deque(maxlen=1000),

            "lock":threading.Lock()
        }



        def probe(
            pad,
            info
        ):

            now=time.perf_counter()

            with counter["lock"]:

                counter["count"]+=1

                counter["times"].append(
                    now
                )


            return Gst.PadProbeReturn.OK



        probe_id=pad.add_probe(
            Gst.PadProbeType.BUFFER,
            probe
        )



        pipeline.set_state(
            Gst.State.PLAYING
        )



        last=0


        while not self.stopped():


            now=time.perf_counter()


            if now-last < 1/STATS_ONLY_UPDATE_FPS:

                continue


            last=now



            with counter["lock"]:

                count=counter["count"]

                times=list(
                    counter["times"]
                )



            while (
                times
                and now-times[0]>1
            ):

                times.pop(0)



            fps=0


            if len(times)>=2:

                fps=(
                    len(times)-1
                ) / (
                    times[-1]-times[0]
                )



            self.event_queue.put(
                make_stats_event(
                    {

                    "device":
                        self.camera.device,

                    "camera":
                        self.camera.name,

                    "backend":
                        "GStreamer fakesink",

                    "realtime_fps":
                        f"{fps:.2f}",

                    "frames":
                        str(count),

                    }
                )
            )



        close_counter_pipeline(
            pipeline,
            pad,
            probe_id
        )


        self.event_queue.put(
            make_stopped_event()
        )
        