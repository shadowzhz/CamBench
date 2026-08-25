import sys
import tkinter as tk

from app.application import CameraFpsApp


def main():

    if sys.platform.startswith("win"):

        print(
            "当前程序面向 Linux/Jetson V4L2 摄像头环境。"
        )


    root = tk.Tk()

    app = CameraFpsApp(root)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.close()



if __name__ == "__main__":

    main()
