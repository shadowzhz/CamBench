import tkinter as tk

from tkinter import ttk



def create_stat_panel(parent):

    panel = ttk.LabelFrame(
        parent,
        text="实时参数",
        padding=10
    )


    keys = (

        ("camera","相机"),

        ("device","设备"),

        ("backend","后端"),

        ("preview","画面"),

        ("format","格式"),

        ("requested_size","请求分辨率"),

        ("actual_size","实际分辨率"),

        ("target_fps","标称 FPS"),

        ("realtime_fps","实时 FPS"),

        ("avg_fps","平均 FPS"),

        ("frames","帧数"),

        ("elapsed","运行时间"),

    )


    variables={}


    for row,(key,title) in enumerate(keys):

        ttk.Label(
            panel,
            text=title,
            style="Panel.TLabel"
        ).grid(
            row=row,
            column=0,
            sticky="w",
            pady=3
        )


        value=tk.StringVar(
            value="-"
        )


        ttk.Label(
            panel,
            textvariable=value,
            style="Panel.TLabel"
        ).grid(
            row=row,
            column=1,
            sticky="e",
            padx=12
        )


        variables[key]=value


    return panel,variables
