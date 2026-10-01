from tkinter import ttk


def setup_style():
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background="#f3f4f6")
    style.configure("Panel.TFrame", background="#ffffff")
    style.configure("TLabel", background="#f3f4f6", font=("Arial", 10))
    style.configure("Panel.TLabel", background="#ffffff", font=("Arial", 10))
    style.configure("Title.TLabel", background="#ffffff", font=("Arial", 14, "bold"))
    style.configure("Status.TLabel", background="#f3f4f6", foreground="#374151")
    style.configure("StatKey.TLabel", font=("Arial", 9), foreground="#555555")
    style.configure("StatVal.TLabel", font=("Arial", 9, "bold"), foreground="#111827")
    style.configure(
        "StatValHighlight.TLabel",
        font=("Arial", 9, "bold"),
        foreground="#16a34a",
    )
    style.configure(
        "Hint.TLabel",
        background="#ffffff",
        foreground="#b45309",
        font=("Arial", 9),
        wraplength=240,
    )
    style.configure("TButton", padding=(8, 5), font=("Arial", 10))
