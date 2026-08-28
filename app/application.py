import base64
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import cv2

from app.styles import setup_style
from app.widgets import create_stat_panel
from camera.diagnostics import diagnose_camera
from camera.scanner import scan_cameras
from core import (
    LOW_FPS_MIN_TARGET,
    LOW_FPS_RATIO_THRESHOLD,
    LOW_FPS_SUSTAINED_UPDATES,
    EventType,
    make_diagnostics_event,
)
from workers.preview_worker import PreviewWorker


class CameraFpsApp:
    """主窗口:左侧控制/统计面板,右侧预览画面。"""

    def __init__(self, root):
        self.root = root
        self.root.title("CAM FPS Test")
        self.root.geometry("1180x720")

        setup_style()

        self.cameras = []
        self.worker = None
        self.queue = queue.Queue(maxsize=2)
        self.preview_image = None
        self._closed = False
        self._low_fps_hits = 0

        self._build_ui()
        self.refresh_cameras()

        # Tk 的控件不允许跨线程操作:采集线程只往队列丢事件,
        # 主线程每 20ms 轮询一次,只刷新最新的一帧/一组统计。
        self.root.after(20, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
    def _build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=12)
        left.grid(row=0, column=0, sticky="ns")

        ttk.Label(left, text="相机控制", style="Title.TLabel").pack(anchor="w")

        self.camera_combo = ttk.Combobox(left, state="readonly")
        self.camera_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self.on_camera_selected()
        )
        self.camera_combo.pack(fill="x", pady=5)

        self.mode_combo = ttk.Combobox(left, state="readonly")
        self.mode_combo.pack(fill="x")

        self.start_button = ttk.Button(left, text="启动", command=self.toggle_camera)
        self.start_button.pack(fill="x", pady=10)

        self.diag_button = ttk.Button(left, text="诊断", command=self.run_diagnostics)
        self.diag_button.pack(fill="x", pady=(0, 10))

        self.hint_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.hint_var, style="Hint.TLabel").pack(fill="x")

        self.stats, self.stat_vars = create_stat_panel(left)
        self.stats.pack(fill="both", expand=True)

        self.preview = tk.Label(self.root, bg="black", text="未启动", fg="white")
        self.preview.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

    def refresh_cameras(self):
        self.cameras = scan_cameras()
        self.camera_combo["values"] = [c.display_name for c in self.cameras]
        if self.cameras:
            self.camera_combo.current(0)
            self.on_camera_selected()

    def on_camera_selected(self):
        index = self.camera_combo.current()
        if index < 0:
            return

        camera = self.cameras[index]
        self.mode_combo["values"] = [m.display_name for m in camera.modes]
        if camera.modes:
            self.mode_combo.current(0)
        else:
            self.mode_combo.set("")

    def _put_event(self, event):
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            pass

    def toggle_camera(self):
        self._reset_low_fps_hint()

        if self.worker:
            self.stop_camera()
            return

        camera = self.cameras[self.camera_combo.current()]
        mode = camera.modes[self.mode_combo.current()]

        self.worker = PreviewWorker(camera, mode, self.queue, True)
        self.worker.start()
        self.start_button.configure(text="停止")

    def stop_camera(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.start_button.configure(text="启动")
        self._reset_low_fps_hint()

    def run_diagnostics(self):
        if self.camera_combo.current() < 0:
            return

        camera = self.cameras[self.camera_combo.current()]
        mode = None
        if camera.modes and self.mode_combo.current() >= 0:
            mode = camera.modes[self.mode_combo.current()]

        # v4l2-ctl/dmesg 调用可能阻塞,放后台线程执行,结果经队列回主线程弹窗
        def work():
            try:
                report = diagnose_camera(camera, mode)
            except Exception as exc:
                report = f"诊断执行失败: {exc}"
            self._put_event(make_diagnostics_event(report))

        threading.Thread(target=work, daemon=True).start()

    def _process_events(self):
        if self._closed:
            return

        latest_frame = None
        latest_stats = None
        try:
            while True:
                event = self.queue.get_nowait()
                if event.type == EventType.FRAME:
                    latest_frame = event.data["frame"]
                    latest_stats = event.data["stats"]
                elif event.type == EventType.STATS:
                    latest_stats = event.data
                elif event.type == EventType.ERROR:
                    messagebox.showerror("错误", event.message)
                elif event.type == EventType.DIAGNOSTICS:
                    messagebox.showinfo("诊断结果", event.message)
        except queue.Empty:
            pass

        if latest_frame is not None:
            self.show_frame(latest_frame)
        if latest_stats is not None:
            self.update_stats(latest_stats)

        self.root.after(20, self._process_events)

    def show_frame(self, frame):
        # Tk 主线程不应反复编码完整分辨率帧;预览只需要缩放到窗口大小,
        # 再以 PNG data URI 喂给 PhotoImage(不需要 Pillow)。
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        max_width = max(self.preview.winfo_width(), 1)
        max_height = max(self.preview.winfo_height(), 1)
        height, width = frame.shape[:2]
        scale = min(max_width / width, max_height / height, 1.0)

        if scale < 1.0:
            frame = cv2.resize(
                frame,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            return

        image = tk.PhotoImage(data=base64.b64encode(encoded))
        self.preview_image = image
        self.preview.configure(image=image)

    def update_stats(self, stats):
        for key, value in stats.items():
            if key in self.stat_vars:
                self.stat_vars[key].set(value)
        self._evaluate_low_fps(stats)

    def _reset_low_fps_hint(self):
        self._low_fps_hits = 0
        if self.hint_var is not None:
            self.hint_var.set("")

    def _evaluate_low_fps(self, stats):
        """实测 FPS 持续低于标称值时,提示用户运行诊断。"""
        if not self.worker:
            return
        try:
            target = float(stats.get("target_fps", "0"))
            realtime = float(stats.get("realtime_fps", "0"))
        except (TypeError, ValueError):
            return

        if target < LOW_FPS_MIN_TARGET:
            self._reset_low_fps_hint()
            return

        if 0 < realtime < target * LOW_FPS_RATIO_THRESHOLD:
            self._low_fps_hits += 1
            if self._low_fps_hits == LOW_FPS_SUSTAINED_UPDATES:
                self.hint_var.set(
                    f"实测 {realtime:.1f} FPS 持续低于标称 {target:.1f} FPS,"
                    "点击「诊断」查看曝光/USB 带宽线索"
                )
        else:
            self._reset_low_fps_hint()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.stop_camera()
        self.root.destroy()
