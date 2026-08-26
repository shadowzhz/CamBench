# CamBench

CamBench 是一个面向 Linux V4L2 摄像头的实时 FPS 测试与预览工具。项目使用 Python、Tkinter、OpenCV、GStreamer 和 `v4l2-ctl`，用于枚举摄像头、读取支持的分辨率/帧率模式，并观察实际采集 FPS。

## 功能

- 自动扫描 `/dev/video*` 摄像头设备。
- 使用 V4L2 能力信息过滤非 Video Capture 节点，并合并同一物理摄像头的多个节点。
- 读取摄像头支持的像素格式、分辨率和 FPS 模式。
- 支持 MJPG、YUYV、YUY2 模式。
- 显示请求分辨率、实际分辨率、目标 FPS、实时 FPS、平均 FPS、帧数和运行时间。
- MJPG 在较高帧率/分辨率场景下优先使用 GStreamer，降低 OpenCV 内部 JPEG 解码造成的性能瓶颈。
- 对 MJPG `>=120 FPS` 模式使用原生 GStreamer appsink 路径，并在 `v4l2src` 输出端统计源 FPS。
- GStreamer 可根据系统环境使用 Jetson `nvv4l2decoder` / `nvvidconv` 或软件 JPEG 解码器。
- 预览和采集线程分离，GUI 仅按固定频率更新画面，避免显示端拖慢采集。
- 摄像头拔出、采集失败和 GStreamer 错误会通过 GUI 事件反馈。

## 项目结构

```text
CamBench/
├── app/                 # Tkinter GUI
├── camera/              # 摄像头扫描、模式解析、采集和 GStreamer 管线
├── core/                # 配置、事件、日志等核心模块
├── workers/             # 摄像头采集/统计 Worker
├── main.py              # 程序入口
└── .gitignore
```

## 环境要求

当前项目主要面向 Linux / Jetson V4L2 摄像头环境。

建议安装：

- Python 3
- Tkinter
- OpenCV (`cv2`)
- NumPy
- PyGObject / GStreamer Python bindings (`gi`)
- GStreamer 1.0
- `v4l2-ctl`（用于枚举设备能力和模式）

Ubuntu/Debian 示例：

```bash
sudo apt install python3-tk python3-opencv python3-numpy \
    python3-gi gir1.2-gstreamer-1.0 v4l-utils \
    gstreamer1.0-tools gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-libav
```

实际所需 GStreamer 插件取决于摄像头输出格式以及平台。Jetson 环境还可使用 NVIDIA 提供的硬件 JPEG 解码链。

## 运行

在仓库根目录执行：

```bash
python3 main.py
```

启动后：

1. 程序扫描 `/dev/video*`。
2. 选择摄像头。
3. 选择摄像头支持的采集模式。
4. 点击“启动”。
5. 查看实时预览和 FPS 统计。

## 采集后端策略

CamBench 会根据模式选择采集路径：

- **MJPG，FPS >= 120**：优先使用原生 GStreamer 高帧率管线；失败时不会伪回退到 OpenCV V4L2，以避免把高帧率模式重新限制在低帧率。
- **MJPG，FPS >= 30**：优先使用 GStreamer，减少 OpenCV JPEG 解码路径可能产生的性能瓶颈。
- **其他模式**：优先尝试 OpenCV V4L2；失败后再尝试 GStreamer。

高帧率 MJPG 路径会在 `v4l2src` 的 source pad 上统计收到的 buffer 数量和时间间隔，因此 GUI 中的实时 FPS 更接近摄像头源端的实际输出，而不是单纯受到 Tkinter 预览刷新频率限制。

## 注意事项

- 摄像头实际能够达到的 FPS 取决于设备、USB 带宽、驱动、分辨率、像素格式、曝光设置以及系统负载。
- GUI 预览刷新频率并不等于摄像头采集 FPS；项目默认预览刷新为 30 FPS，但采集统计可以高于此值。
- `v4l2-ctl` 不存在时，项目会使用预置的常见模式作为回退，因此建议在完整 Linux 环境中安装 `v4l-utils`。
- 高帧率 MJPG 模式需要可用的 GStreamer JPEG 解码器。

## 许可证

当前仓库未声明开源许可证。除非仓库后续添加许可证文件，否则请不要默认将代码视为可自由再分发的开源软件。
