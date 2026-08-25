import tkinter as tk

from tkinter import ttk,messagebox

import queue
import cv2
import base64
import time


from app.styles import setup_style
from app.widgets import create_stat_panel


from camera.scanner import scan_cameras


from workers.preview_worker import PreviewWorker
from workers.counter_worker import CounterWorker


from core.events import EventType



class CameraFpsApp:


    def __init__(
        self,
        root
    ):

        self.root=root

        self.root.title(
            "CAM FPS Test"
        )

        self.root.geometry(
            "1180x720"
        )


        setup_style()



        self.cameras=[]

        self.worker=None


        self.queue=queue.Queue(
            maxsize=2
        )


        self.preview_enabled=True


        self.preview_image=None


        self.build_ui()



        self.refresh_cameras()



        self.root.after(
            20,
            self.process_events
        )


        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.close
        )



    def build_ui(self):


        self.root.columnconfigure(
            1,
            weight=1
        )


        self.root.rowconfigure(
            0,
            weight=1
        )



        left=ttk.Frame(
            self.root,
            padding=12
        )


        left.grid(
            row=0,
            column=0,
            sticky="ns"
        )



        ttk.Label(
            left,
            text="相机控制",
            style="Title.TLabel"
        ).pack(
            anchor="w"
        )



        self.camera_combo=ttk.Combobox(
            left,
            state="readonly"
        )


        self.camera_combo.pack(
            fill="x",
            pady=5
        )



        self.mode_combo=ttk.Combobox(
            left,
            state="readonly"
        )


        self.mode_combo.pack(
            fill="x"
        )



        self.start_button=ttk.Button(
            left,
            text="启动",
            command=self.toggle_camera
        )


        self.start_button.pack(
            fill="x",
            pady=10
        )



        self.stats,self.stat_vars=create_stat_panel(
            left
        )


        self.stats.pack(
            fill="both",
            expand=True
        )



        self.preview=tk.Label(
            self.root,
            bg="black",
            text="未启动",
            fg="white"
        )


        self.preview.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=10,
            pady=10
        )



    def refresh_cameras(self):

        self.cameras=scan_cameras()


        self.camera_combo["values"]=[
            x.display_name
            for x in self.cameras
        ]


        if self.cameras:

            self.camera_combo.current(0)

            self.on_camera_selected()



    def on_camera_selected(self):

        index=self.camera_combo.current()

        if index<0:
            return


        camera=self.cameras[index]


        self.mode_combo["values"]=[
            m.display_name
            for m in camera.modes
        ]


        if camera.modes:

            self.mode_combo.current(0)



    def toggle_camera(self):

        if self.worker:

            self.stop_camera()

            return



        camera=self.cameras[
            self.camera_combo.current()
        ]


        mode=camera.modes[
            self.mode_combo.current()
        ]



        self.worker=PreviewWorker(
            camera,
            mode,
            self.queue,
            self.preview_enabled
        )


        self.worker.start()



        self.start_button.configure(
            text="停止"
        )



    def stop_camera(self):

        if self.worker:

            self.worker.stop()

            self.worker=None



        self.start_button.configure(
            text="启动"
        )



    def process_events(self):


        try:

            while True:

                event=self.queue.get_nowait()


                if event.type==EventType.FRAME:

                    self.show_frame(
                        event.data["frame"]
                    )


                    self.update_stats(
                        event.data["stats"]
                    )


                elif event.type==EventType.STATS:

                    self.update_stats(
                        event.data
                    )


                elif event.type==EventType.ERROR:

                    messagebox.showerror(
                        "错误",
                        event.message
                    )


        except queue.Empty:

            pass



        self.root.after(
            20,
            self.process_events
        )



    def show_frame(self,frame):

        frame=cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB
        )


        image=tk.PhotoImage(
            data=base64.b64encode(
                cv2.imencode(
                    ".png",
                    frame
                )[1]
            )
        )


        self.preview_image=image

        self.preview.configure(
            image=image
        )



    def update_stats(self,stats):

        for k,v in stats.items():

            if k in self.stat_vars:

                self.stat_vars[k].set(
                    v
                )



    def close(self):

        self.stop_camera()

        self.root.destroy()
        