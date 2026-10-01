# CamBench

CamBench 是一个面向 Windows 和 Linux 的跨平台摄像头实时 FPS 测试与预览诊断工具。项目使用 Python、Tkinter、OpenCV、GStreamer（Linux）与 DirectShow / MediaFoundation（Windows），用于枚举摄像头、配置分辨率/帧率模式，并观察实际采集 FPS。

## 功能

- **跨平台支持**：支持 Linux (V4L2 / GStreamer) 与 Windows (DirectShow / MediaFoundation)。
- **即插即用（热插拔自动感知）**：后台自动监听摄像头插入与拔出事件（Linux 支持 `pyudev` netlink 监听与 sysfs 轮询；Windows 支持设备动态跟踪），插入新设备时自动识别并装载，无需重启软件；同时提供「🔄 刷新」按钮备用。
- **分级模式选择**：采用「编码格式 -> 分辨率 -> 目标帧率」三级联动选择器，清晰直观，告别混乱冗长的模式列表。
- **硬件能力清单一览**：点击「📋 硬件能力清单」可打开全量参数矩阵表格，一眼看全相机硬件支持的所有格式、离散分辨率与最高/全量帧率组合，双击任意行即可直接装载。
- **即选即切（无感切换）**：在画面预览运行中任意切换格式、分辨率或帧率时，系统自动平滑重启采集管线，无需用户反复手动启停。
- 自动扫描可用摄像头：Linux 扫描 `/dev/video*` 并智能合并物理节点；Windows 自动探测设备索引并结合 PowerShell 获取设备名称。
- 使用 V4L2 能力信息过滤非 Video Capture 节点，并合并同一物理摄像头的多个节点。
- 优先通过 V4L2 ioctl（`VIDIOC_ENUM_FMT` / `ENUM_FRAMESIZES` / `ENUM_FRAMEINTERVALS`）直接枚举像素格式、分辨率和 FPS 模式，不依赖 `v4l2-ctl`；ioctl 不可用时回退到解析 `v4l2-ctl --list-formats-ext` 文本。
- 支持 MJPG、YUYV、YUY2 模式。
- 显示请求分辨率、实际分辨率、目标 FPS、实时 FPS、平均 FPS、帧数和运行时间。
- 实测 FPS 持续低于标称值时，GUI 自动给出"跑不满"提示。
- 内置诊断功能：
  - **Linux**：USB 总线速度（sysfs）、自动曝光状态（含切换手动曝光的命令）、内核日志中的 uvcvideo 带宽告警。
  - **Windows**：自动曝光低光补偿建议、USB 3.0/2.0 链路建议及主机控制器探测。
- MJPG 在较高帧率/分辨率场景下优先使用 GStreamer，降低 OpenCV 内部 JPEG 解码造成的性能瓶颈。
- 对 MJPG `>=120 FPS` 模式使用原生 GStreamer appsink 路径，并在 `v4l2src` 输出端统计源 FPS。
- GStreamer 可根据系统环境使用 Jetson `nvv4l2decoder` / `nvvidconv` 或软件 JPEG 解码器。
- 预览和采集线程分离，GUI 仅按固定频率更新画面，避免显示端拖慢采集。
- 摄像头拔出、采集失败和 GStreamer 错误会通过 GUI 事件反馈。

## 项目结构

```text
CamBench/
├── main.py              # 程序入口
├── core.py              # 配置、Worker->GUI 事件、日志
├── app/                 # Tkinter GUI(主窗口、样式、统计面板)
├── camera/              # 设备扫描、V4L2 枚举、采集后端与 GStreamer 管线
├── workers/             # 采集线程(与 GUI 通过事件队列通信)
└── tests/               # 单元测试
```

## 环境要求

### Linux (Ubuntu/Debian 示例)

```bash
sudo apt install python3-tk python3-opencv python3-numpy \
    python3-gi gir1.2-gstreamer-1.0 v4l-utils \
    gstreamer1.0-tools gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-libav
```

### Windows

建议安装 Python 3.8+ 并通过 pip 安装：

```bash
pip install opencv-python numpy
```
*注：Tkinter 通常已随官方 Windows Python 安装包一同安装。*
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

## 诊断"跑不满帧率"

实测 FPS 明显低于标称值时，通常不是解码瓶颈，而是以下三个原因之一。点击 GUI 中的「诊断」按钮可以直接查看对应线索：

1. **自动曝光**：光线不足时相机会自动延长曝光时间，把帧率压到环境光频率的倍数（如标称 120 FPS 实际 25 FPS）。诊断会读取 `auto_exposure` 状态并给出切换手动曝光的命令。
2. **USB 带宽**：USB 2.0（480 Mbps）无法承载高分辨率高帧率模式；多相机共享同一 USB 总线时也会互相挤占。诊断读取 sysfs 中的 USB 端口速度。
3. **驱动带宽协商失败**：`uvcvideo` 驱动在带宽不足时会降级，并在内核日志中留下告警。诊断会检查 `dmesg` / `journalctl`。

若要单独排查采集层损耗，可对比 GUI 中 GStreamer 管线源端统计的实时 FPS（`camera/pipeline.py` 的 fakesink 计数路径）与驱动层极限；也可使用 `v4l2-ctl --stream-mmap --stream-count=200` 直接测量驱动层帧率。

## 注意事项

- 摄像头实际能够达到的 FPS 取决于设备、USB 带宽、驱动、分辨率、像素格式、曝光设置以及系统负载。
- GUI 预览刷新频率并不等于摄像头采集 FPS；项目默认预览刷新为 30 FPS，但采集统计可以高于此值。
- 模式枚举优先走 V4L2 ioctl，因此未安装 `v4l2-ctl` 时仍能正常识别大多数 UVC 摄像头；个别不支持帧间隔枚举的驱动会回退到预置的常见模式。
- 高帧率 MJPG 模式需要可用的 GStreamer JPEG 解码器。
- 运行单元测试：`python3 -m unittest discover -s tests`。

## 许可证

当前仓库未声明开源许可证。除非仓库后续添加许可证文件，否则请不要默认将代码视为可自由再分发的开源软件。
