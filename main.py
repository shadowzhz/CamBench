"""
CamBench 应用程序入口。

职责:
1. 检测运行平台(Windows 或 Linux);
2. 创建 Tkinter 根窗口并实例化主控制器 CameraFpsApp;
3. 启动 GUI 事件主循环,并在捕获 Ctrl+C 时安全终止后台线程。
"""

import sys
import tkinter as tk

from app.application import CameraFpsApp


def main():
    # 启动前自检当前操作系统,便于排查平台专用后端加载情况
    if sys.platform.startswith("win"):
        print("CamBench 已启动: 运行于 Windows (DirectShow/MediaFoundation 模式)")
    else:
        print("CamBench 已启动: 运行于 Linux/V4L2 模式")

    root = tk.Tk()
    app = CameraFpsApp(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        # 终端捕获 Ctrl+C 时确保采集线程与热插拔监控线程正常停止
        app.close()


if __name__ == "__main__":
    main()
