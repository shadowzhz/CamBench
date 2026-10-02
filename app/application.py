"""
GUI 主控制器模块 (Tkinter)。

【核心架构与工作流程】
1. 视图布局:
   - 左侧: 静态控制与实时参数面板 (相机选择、格式/分辨率/帧率三级联动、启停/诊断按钮、双列统计数据);
   - 右侧: 视频预览视口 (支持实时等比例缩放与水平镜像翻转)。
2. 线程隔离与事件循环:
   - 主线程运行 Tkinter 事件循环，通过 after(20, self._process_events) 定时消费后台队列;
   - 永远不在主线程进行摄像头打开、读帧、ioctl 查询或网络探测等阻塞调用。
3. 模式三级联动与平滑重启:
   - 改变相机 -> 自动刷新可选格式列表 -> 自动刷新对应分辨率 -> 自动刷新对应帧率;
   - 预览运行中修改任一级别下拉框时，调用 _restart_camera() 无感平滑重启底层采集 Worker。
4. 热插拔动态响应:
   - DeviceMonitor 监测到系统设备增删后抛出 DEVICES_CHANGED 事件;
   - 主界面自动更新下拉列表，若插入新相机则自动聚焦，若拔出当前运行相机则安全停止并弹窗告警。
"""

import base64
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import cv2

from app.styles import setup_style
from app.widgets import CapabilitiesWindow, ScrollableFrame, create_stat_panel
from camera.diagnostics import diagnose_camera
from camera.modes import (
    find_mode,
    get_available_formats,
    get_fps_for_resolution,
    get_resolutions_for_format,
)
from camera.monitor import DeviceMonitor
from camera.scanner import scan_cameras
from core import (
    LOW_FPS_MIN_TARGET,
    LOW_FPS_RATIO_THRESHOLD,
    LOW_FPS_SUSTAINED_UPDATES,
    EventType,
    make_diagnostics_event,
    make_devices_changed_event,
    log,
)
from workers.preview_worker import PreviewWorker


class CameraFpsApp:
    """主窗口:左侧控制/统计面板,右侧预览画面。"""

    def __init__(self, root):
        self.root = root
        self.root.title("CAM FPS Test")
        self.root.geometry("1180x720")
        self.root.minsize(980, 560)

        setup_style()

        self.cameras = []
        self.worker = None
        self.queue = queue.Queue(maxsize=2)
        self.preview_image = None
        self._closed = False
        self._low_fps_hits = 0

        self._build_ui()

        # 热插拔监控器
        self.monitor = DeviceMonitor(on_change=self._on_devices_changed)
        self.refresh_cameras()
        self.monitor.start()

        # Tk 的控件不允许跨线程操作:采集线程只往队列丢事件,
        # 主线程每 20ms 轮询一次,只刷新最新的一帧/一组统计。
        self.root.after(20, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _on_devices_changed(self, added, removed):
        self._put_event(make_devices_changed_event(added, removed))

    def _build_ui(self):
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=(12, 10))
        left.grid(row=0, column=0, sticky="nsw")

        # 顶部:相机选择与刷新按钮
        cam_header = ttk.Frame(left)
        cam_header.pack(fill="x", pady=(0, 4))
        ttk.Label(cam_header, text="相机选择", style="Title.TLabel").pack(side="left")
        self.refresh_button = ttk.Button(
            cam_header, text="🔄 刷新", width=7, command=self.refresh_cameras
        )
        self.refresh_button.pack(side="right")

        self.camera_combo = ttk.Combobox(left, state="readonly")
        self.camera_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self.on_camera_selected()
        )
        self.camera_combo.pack(fill="x", pady=(0, 6))

        # 采集模式设置分组(格式 -> 分辨率 -> 帧率)
        mode_frame = ttk.LabelFrame(left, text="采集模式设置", padding=6)
        mode_frame.pack(fill="x", pady=(0, 6))

        grid_opts = {"sticky": "w", "pady": 2}
        ttk.Label(mode_frame, text="编码格式:").grid(row=0, column=0, **grid_opts)
        self.format_combo = ttk.Combobox(mode_frame, state="readonly", width=14)
        self.format_combo.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=2)
        self.format_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self.on_format_selected(trigger_restart=True)
        )

        ttk.Label(mode_frame, text="分辨率:").grid(row=1, column=0, **grid_opts)
        self.res_combo = ttk.Combobox(mode_frame, state="readonly", width=14)
        self.res_combo.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=2)
        self.res_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self.on_resolution_selected(trigger_restart=True)
        )

        ttk.Label(mode_frame, text="目标帧率:").grid(row=2, column=0, **grid_opts)
        self.fps_combo = ttk.Combobox(mode_frame, state="readonly", width=14)
        self.fps_combo.grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=2)
        self.fps_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self.on_fps_selected(trigger_restart=True)
        )
        mode_frame.columnconfigure(1, weight=1)

        self.caps_button = ttk.Button(
            mode_frame, text="📋 硬件能力清单", command=self.show_capabilities_window
        )
        self.caps_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 2))

        # 操作按钮并排放在同一行: [启动]  [诊断]
        btn_row = ttk.Frame(left)
        btn_row.pack(fill="x", pady=(0, 6))

        self.start_button = ttk.Button(btn_row, text="启动", command=self.toggle_camera)
        self.start_button.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.diag_button = ttk.Button(btn_row, text="诊断", command=self.run_diagnostics)
        self.diag_button.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.mirror_var = tk.BooleanVar(value=True)
        self.mirror_check = ttk.Checkbutton(btn_row, text="镜像", variable=self.mirror_var)
        self.mirror_check.pack(side="right")

        self.hint_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.hint_var, style="Hint.TLabel").pack(fill="x", pady=(0, 4))

        self.stats, self.stat_vars = create_stat_panel(left)
        self.stats.pack(fill="x", expand=False)

        self.preview = tk.Label(self.root, bg="black", text="未启动", fg="white")
        self.preview.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

    def refresh_cameras(self, preferred_device=None):
        current_dev = preferred_device
        if current_dev is None and hasattr(self, "camera_combo"):
            idx = self.camera_combo.current()
            if isinstance(idx, int) and idx >= 0 and self.cameras and idx < len(self.cameras):
                current_dev = self.cameras[idx].device

        self.cameras = scan_cameras()
        self.camera_combo["values"] = [c.display_name for c in self.cameras]

        if not self.cameras:
            self.camera_combo.set("")
            self.format_combo["values"] = []
            self.format_combo.set("")
            self.res_combo["values"] = []
            self.res_combo.set("")
            self.fps_combo["values"] = []
            self.fps_combo.set("")
            self.hint_var.set("未检测到可用摄像头,请接入摄像头后点击刷新")
            return

        target_idx = 0
        if current_dev:
            for idx, cam in enumerate(self.cameras):
                if cam.device == current_dev:
                    target_idx = idx
                    break

        self.camera_combo.current(target_idx)
        self.on_camera_selected(trigger_restart=False)

    def on_camera_selected(self, trigger_restart=False):
        """相机下拉框变更回调: 重新拉取该相机的格式清单，并依次级联触发。"""
        index = self.camera_combo.current()
        if index < 0 or index >= len(self.cameras):
            return

        camera = self.cameras[index]
        formats = get_available_formats(camera.modes)
        self.format_combo["values"] = formats
        if formats:
            self.format_combo.current(0)
            self.on_format_selected(trigger_restart=trigger_restart)
        else:
            self.format_combo.set("")
            self.res_combo.set("")
            self.fps_combo.set("")

    def on_format_selected(self, trigger_restart=True):
        """格式变更回调: 根据所选格式提取其支持的所有离散分辨率，并级联更新。"""
        fmt = self.format_combo.get()
        if not fmt or self.camera_combo.current() < 0:
            return

        camera = self.cameras[self.camera_combo.current()]
        resolutions = get_resolutions_for_format(camera.modes, fmt)
        self.res_combo["values"] = [f"{w}x{h}" for w, h in resolutions]
        if resolutions:
            self.res_combo.current(0)
            self.on_resolution_selected(trigger_restart=trigger_restart)
        else:
            self.res_combo.set("")
            self.fps_combo.set("")

    def on_resolution_selected(self, trigger_restart=True):
        """分辨率变更回调: 提取当前(格式, 分辨率)下硬件支持的所有有效帧率列表。"""
        res_str = self.res_combo.get()
        fmt = self.format_combo.get()
        if not res_str or not fmt or self.camera_combo.current() < 0:
            return

        try:
            w_str, h_str = res_str.split("x", 1)
            w, h = int(w_str), int(h_str)
        except ValueError:
            return

        camera = self.cameras[self.camera_combo.current()]
        fps_list = get_fps_for_resolution(camera.modes, fmt, w, h)
        self.fps_combo["values"] = [f"{fps:.2f} FPS" for fps in fps_list]
        if fps_list:
            self.fps_combo.current(0)
            self.on_fps_selected(trigger_restart=trigger_restart)
        else:
            self.fps_combo.set("")

    def on_fps_selected(self, trigger_restart=True):
        """帧率变更回调: 若摄像头正在预览运行，即选即切，平滑重启采集。"""
        if trigger_restart and self.worker is not None:
            self._restart_camera()

    def get_current_selected_mode(self):
        index = self.camera_combo.current()
        if index < 0 or index >= len(self.cameras):
            return None

        camera = self.cameras[index]
        fmt = self.format_combo.get()
        res_str = self.res_combo.get()
        fps_str = self.fps_combo.get()

        if not fmt or not res_str:
            return camera.modes[0] if camera.modes else None

        try:
            w, h = (int(x) for x in res_str.split("x", 1))
            fps = float(fps_str.replace("FPS", "").strip()) if fps_str else 30.0
        except ValueError:
            return camera.modes[0] if camera.modes else None

        mode = find_mode(camera.modes, fmt, w, h, fps)
        return mode or (camera.modes[0] if camera.modes else None)

    def show_capabilities_window(self):
        index = self.camera_combo.current()
        if index < 0 or index >= len(self.cameras):
            messagebox.showinfo("提示", "未选择摄像头")
            return
        camera = self.cameras[index]
        CapabilitiesWindow(self.root, camera, on_select_mode=self.select_mode_direct)

    def select_mode_direct(self, fmt, width, height, fps):
        """从能力清单表格中直接装载指定模式,并支持运行中实时切换。"""
        self.format_combo.set(fmt)
        camera = self.cameras[self.camera_combo.current()]
        resolutions = get_resolutions_for_format(camera.modes, fmt)
        self.res_combo["values"] = [f"{w}x{h}" for w, h in resolutions]
        self.res_combo.set(f"{width}x{height}")

        fps_list = get_fps_for_resolution(camera.modes, fmt, width, height)
        self.fps_combo["values"] = [f"{f:.2f} FPS" for f in fps_list]
        self.fps_combo.set(f"{fps:.2f} FPS")

        if self.worker is not None:
            self._restart_camera()

    def _restart_camera(self):
        """
        平滑重启采集线程以切换到新模式(即选即切)。
        先停止当前正在读帧的 Worker，再按新选取的模式无阻塞启动新 Worker。
        """
        self._reset_low_fps_hint()
        if self.worker:
            self.worker.stop()
            self.worker = None

        index = self.camera_combo.current()
        if index < 0 or index >= len(self.cameras):
            return

        camera = self.cameras[index]
        mode = self.get_current_selected_mode()
        if not mode:
            return

        self.worker = PreviewWorker(camera, mode, self.queue, True)
        self.worker.start()
        self.start_button.configure(text="停止")

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

        index = self.camera_combo.current()
        if index < 0 or index >= len(self.cameras):
            messagebox.showwarning("提示", "请先选择可用摄像头")
            return

        camera = self.cameras[index]
        mode = self.get_current_selected_mode()
        if not mode:
            messagebox.showwarning("提示", "当前摄像头无可用的采集模式")
            return

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
        mode = self.get_current_selected_mode()

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
                    self.stop_camera()
                    self.preview.configure(image="", text="打开相机失败")
                    self.hint_var.set("打开相机失败，详情见弹窗")
                    messagebox.showerror("打开相机失败", event.message)
                elif event.type == EventType.DIAGNOSTICS:
                    messagebox.showinfo("诊断结果", event.message)
                elif event.type == EventType.DEVICES_CHANGED:
                    added = event.data.get("added", [])
                    removed = event.data.get("removed", [])
                    log(f"app: devices changed (added={added}, removed={removed})")
                    if added:
                        self.hint_var.set(f"检测到新设备接入: {', '.join(added)}")
                    elif removed:
                        self.hint_var.set(f"设备已移除: {', '.join(removed)}")
                    if self.worker and any(
                        rem in self.worker.camera.device_candidates for rem in removed
                    ):
                        self.stop_camera()
                        self.preview.configure(image="", text="摄像头已拔出")
                        messagebox.showwarning("设备已拔出", "正在使用的摄像头已被移除!")
                    # 如果有新加入设备,优先切换到新设备
                    preferred = added[0] if (added and not self.worker) else None
                    self.refresh_cameras(preferred_device=preferred)
                elif event.type == EventType.DEVICE_LOST:
                    self.stop_camera()
                    self.preview.configure(image="", text="摄像头连接断开")
                    self.hint_var.set("设备连接断开")
                    self.refresh_cameras()
        except queue.Empty:
            pass

        if latest_frame is not None:
            self.show_frame(latest_frame)
        if latest_stats is not None:
            self.update_stats(latest_stats)

        self.root.after(20, self._process_events)

    def show_frame(self, frame):
        # 水平镜像翻转(默认开启,可通过界面复选框随时切换)
        if getattr(self, "mirror_var", None) is None or self.mirror_var.get():
            frame = cv2.flip(frame, 1)

        # Tk 主线程不应反复编码完整分辨率帧;预览只需要缩放到窗口大小,
        # 再以 PNG data URI 喂给 PhotoImage(不需要 Pillow)。
        # 注意: cv2.imencode 默认接收 BGR 格式并在编码 PNG 时自动转为标准 RGB 顺序,
        # 切勿在此处调用 cvtColor(BGR2RGB), 否则会导致 R/B 通道颠倒出现蓝脸。
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
                display_val = value
                if key == "backend" and " /dev/" in str(value):
                    display_val = str(value).split(" /dev/")[0]
                self.stat_vars[key].set(display_val)
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
        if hasattr(self, "monitor") and self.monitor:
            self.monitor.stop()
        self.stop_camera()
        self.root.destroy()
