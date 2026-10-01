"""
自定义 GUI 控件与子窗口组件模块。

包含:
1. create_stat_panel: 紧凑型双列实时参数显示面板;
2. CapabilitiesWindow: 基于 ttk.Treeview 的摄像头全量硬件能力矩阵弹窗;
3. ScrollableFrame: 带有鼠标滚轮事件支持的纵向自适应滚动容器。
"""

from tkinter import ttk

import tkinter as tk


def create_stat_panel(parent):
    """
    创建左侧'实时参数'显示面板。

    【设计要点】
    1. 返回 (panel_widget, variables_dict) 元组，GUI 通过向 variables_dict[key].set(val)
       写入数据完成无闪烁刷新;
    2. 采用双列 (4 栏: Key1/Val1/Key2/Val2) 紧凑排布，将原先 12 行压缩至 6 行，
       彻底避免纵向溢出屏幕的问题。
    """
    panel = ttk.LabelFrame(parent, text="实时参数", padding=(8, 6))

    all_keys = (
        "camera", "device", "backend", "preview", "format",
        "requested_size", "actual_size", "target_fps",
        "realtime_fps", "avg_fps", "frames", "elapsed"
    )
    variables = {k: tk.StringVar(value="-") for k in all_keys}

    # 左右双列排布: 将 12 行压缩至 6 行, 高度直降 50%
    layout = [
        (("device", "设备:"), ("preview", "画面:")),
        (("backend", "后端:"), ("format", "格式:")),
        (("requested_size", "请求:"), ("actual_size", "实际:")),
        (("target_fps", "标称:"), ("realtime_fps", "实时:")),
        (("avg_fps", "平均:"), ("frames", "帧数:")),
        (("elapsed", "运行:"), None),
    ]

    panel.columnconfigure(1, weight=1)
    panel.columnconfigure(3, weight=1)

    for row, (left_item, right_item) in enumerate(layout):
        # 左列
        l_key, l_title = left_item
        ttk.Label(panel, text=l_title, style="StatKey.TLabel").grid(
            row=row, column=0, sticky="w", padx=(1, 2), pady=2
        )
        l_style = "StatValHighlight.TLabel" if l_key == "realtime_fps" else "StatVal.TLabel"
        ttk.Label(panel, textvariable=variables[l_key], style=l_style).grid(
            row=row, column=1, sticky="w", padx=(0, 6), pady=2
        )

        # 右列
        if right_item:
            r_key, r_title = right_item
            ttk.Label(panel, text=r_title, style="StatKey.TLabel").grid(
                row=row, column=2, sticky="w", padx=(4, 2), pady=2
            )
            r_style = "StatValHighlight.TLabel" if r_key == "realtime_fps" else "StatVal.TLabel"
            ttk.Label(panel, textvariable=variables[r_key], style=r_style).grid(
                row=row, column=3, sticky="w", padx=(0, 1), pady=2
            )

    return panel, variables


class ScrollableFrame(ttk.Frame):
    """可纵向滚动的轻量自适应容器,在小屏幕或小窗口下防止内容被裁切。"""

    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)

        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, width=320)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_content = ttk.Frame(self.canvas)

        self.scrollable_content.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self._window_id = self.canvas.create_window(
            (0, 0), window=self.scrollable_content, anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self._window_id, width=e.width),
        )

        # 仅在鼠标移入左面板区域时激活滚轮,避免干扰右侧预览
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    def _unbind_wheel(self, _event):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        if event.delta:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class CapabilitiesWindow(tk.Toplevel):
    """
    摄像头硬件能力(格式/分辨率/帧率)一览弹窗。

    以表格 (ttk.Treeview) 形式清晰呈现当前摄像头固件上报的全部支持模式。
    用户双击任意行或点击'应用选中的模式'，可通过回调将参数回填至主界面联动框并平滑生效。
    """

    def __init__(self, parent, camera, on_select_mode=None):
        super().__init__(parent)
        self.camera = camera
        self.on_select_mode = on_select_mode
        self.title(f"硬件能力清单 - {camera.name}")
        self.geometry("640x480")
        self.minsize(500, 320)

        self._build_ui()
        self._populate_data()

    def _build_ui(self):
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill="x")

        title = f"{self.camera.name} ({self.camera.device})"
        ttk.Label(top_frame, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        desc = f"总线/接口: {self.camera.bus_info or '未知'} | 支持共 {len(self.camera.modes)} 个模式组合"
        ttk.Label(top_frame, text=desc, foreground="#666666").pack(anchor="w", pady=(2, 0))

        # 表格区
        table_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        table_frame.pack(fill="both", expand=True)

        columns = ("format", "resolution", "max_fps", "all_fps")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.tree.heading("format", text="编码格式")
        self.tree.heading("resolution", text="分辨率")
        self.tree.heading("max_fps", text="最高帧率")
        self.tree.heading("all_fps", text="支持的所有帧率 (FPS)")

        self.tree.column("format", width=90, anchor="center")
        self.tree.column("resolution", width=120, anchor="center")
        self.tree.column("max_fps", width=90, anchor="center")
        self.tree.column("all_fps", width=260, anchor="w")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_double_click)

        # 底部操作栏
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack(fill="x")

        ttk.Label(btn_frame, text="提示: 双击任意行可直接选择并装载该模式", foreground="#888888").pack(
            side="left"
        )
        ttk.Button(btn_frame, text="应用选中的模式", command=self._apply_selected).pack(
            side="right"
        )

    def _populate_data(self):
        from camera.modes import group_modes
        grouped = group_modes(self.camera.modes)

        self._item_map = {}
        for fmt, res_map in grouped.items():
            # 分辨率按面积降序
            sorted_res = sorted(res_map.keys(), key=lambda r: (-(r[0] * r[1]), -r[0]))
            for w, h in sorted_res:
                fps_list = res_map[(w, h)]
                max_fps_str = f"{fps_list[0]:.2f} FPS" if fps_list else "-"
                all_fps_str = ", ".join(f"{f:.2f}" for f in fps_list)

                item_id = self.tree.insert(
                    "",
                    "end",
                    values=(fmt, f"{w}x{h}", max_fps_str, all_fps_str),
                )
                self._item_map[item_id] = (fmt, w, h, fps_list[0] if fps_list else 30.0)

    def _on_double_click(self, _event):
        self._apply_selected()

    def _apply_selected(self):
        selected = self.tree.selection()
        if not selected or not self.on_select_mode:
            return
        item_id = selected[0]
        if item_id in self._item_map:
            fmt, w, h, fps = self._item_map[item_id]
            self.on_select_mode(fmt, w, h, fps)
            self.destroy()
