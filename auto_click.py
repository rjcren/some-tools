import tkinter as tk
import tkinter.ttk as ttk
import tkinter.messagebox
import time
from threading import Thread, Event
import keyboard
import sys
import pydirectinput  # 替代pyautogui，专为游戏优化


class AutoclickerApp:
    def __init__(self, master):
        self.master = master
        self.master.title("Unity游戏自动点击器 - 按F4启停")
        self.master.geometry("400x180")
        self.master.resizable(False, False)

        # ---------- 第一行：间隔 & 按键 ----------
        row1 = ttk.Frame(self.master)
        row1.pack(pady=5, fill='x')

        ttk.Label(row1, text="间隔(ms):").pack(side='left', padx=5)
        self.ms_entry = ttk.Entry(row1, width=8)
        self.ms_entry.pack(side='left', padx=5)
        self.ms_entry.insert(0, "100")

        ttk.Label(row1, text="按键:").pack(side='left', padx=5)
        self.key_combo = ttk.Combobox(row1, values=["左键", "右键", "中键"], width=6)
        self.key_combo.current(0)
        self.key_combo.pack(side='left', padx=5)

        # ---------- 第二行：窗口标题（可选激活） ----------
        row2 = ttk.Frame(self.master)
        row2.pack(pady=5, fill='x')

        self.activate_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="激活窗口", variable=self.activate_var,
                        command=self.toggle_window_entry).pack(side='left', padx=5)

        ttk.Label(row2, text="窗口标题:").pack(side='left', padx=5)
        self.window_entry = ttk.Entry(row2, width=20, state='disabled')
        self.window_entry.pack(side='left', padx=5)
        self.window_entry.insert(0, "游戏窗口标题")

        # ---------- 第三行：固定坐标 ----------
        row3 = ttk.Frame(self.master)
        row3.pack(pady=5, fill='x')

        self.fixed_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row3, text="固定坐标", variable=self.fixed_var,
                        command=self.toggle_coord_entry).pack(side='left', padx=5)

        ttk.Label(row3, text="X:").pack(side='left')
        self.x_entry = ttk.Entry(row3, width=5, state='disabled')
        self.x_entry.pack(side='left', padx=2)
        ttk.Label(row3, text="Y:").pack(side='left')
        self.y_entry = ttk.Entry(row3, width=5, state='disabled')
        self.y_entry.pack(side='left', padx=2)

        # ---------- 按钮 ----------
        btn_frame = ttk.Frame(self.master)
        btn_frame.pack(pady=10)
        self.start_btn = ttk.Button(btn_frame, text="开始 (F4)", command=self.start_clicker)
        self.start_btn.pack(side='left', padx=10)
        self.stop_btn = ttk.Button(btn_frame, text="停止 (F4)", command=self.stop_clicker)
        self.stop_btn.pack(side='left', padx=10)

        # ---------- 状态 ----------
        self.status_label = ttk.Label(self.master, text="就绪")
        self.status_label.pack(pady=2)

        # ---------- 线程控制 ----------
        self.clicker_thread = None
        self.exit_event = Event()

        # 注册F4热键
        keyboard.on_press_key("F4", self.on_f4_press)

        # 关闭窗口时清理资源
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ---------- 控件联动 ----------
    def toggle_window_entry(self):
        state = 'normal' if self.activate_var.get() else 'disabled'
        self.window_entry.config(state=state)

    def toggle_coord_entry(self):
        state = 'normal' if self.fixed_var.get() else 'disabled'
        self.x_entry.config(state=state)
        self.y_entry.config(state=state)

    # ---------- 核心逻辑 ----------
    def start_clicker(self):
        # 验证间隔
        try:
            ms = int(self.ms_entry.get())
            if ms < 50:
                tk.messagebox.showwarning("错误", "间隔必须 ≥ 50 毫秒")
                return
        except ValueError:
            tk.messagebox.showwarning("错误", "请输入有效整数毫秒")
            return

        # 验证坐标（如果启用）
        fixed = self.fixed_var.get()
        if fixed:
            try:
                x = int(self.x_entry.get())
                y = int(self.y_entry.get())
                if x < 0 or y < 0:
                    raise ValueError
            except ValueError:
                tk.messagebox.showwarning("错误", "请输入有效的正整数坐标")
                return
        else:
            x = y = None

        # 获取窗口标题（如果启用）
        activate = self.activate_var.get()
        window_title = self.window_entry.get().strip() if activate else None

        # 如果已经运行则先停止（防止重复启动）
        if self.clicker_thread and self.clicker_thread.is_alive():
            self.stop_clicker()
            # 等待线程结束
            self.clicker_thread.join(timeout=0.5)

        self.exit_event.clear()
        self.clicker_thread = Thread(target=self.run_clicker, args=(ms, fixed, x, y, window_title))
        self.clicker_thread.daemon = True
        self.clicker_thread.start()
        self.status_label.config(text="运行中...")

    def run_clicker(self, interval_ms, fixed, fx, fy, window_title):
        btn_map = {"左键": "left", "右键": "right", "中键": "middle"}
        button = btn_map.get(self.key_combo.get(), "left")

        # 关闭pydirectinput的防故障功能（可选）
        pydirectinput.FAILSAFE = False

        try:
            while not self.exit_event.is_set():
                if fixed:
                    # 固定坐标点击（会自动移动鼠标并点击）
                    pydirectinput.click(fx, fy, button=button)
                else:
                    # 当前位置点击
                    pydirectinput.click(button=button)

                time.sleep(interval_ms / 1000.0)
        except Exception as e:
            self.handle_exception(e)
            self.status_label.config(text="发生错误，已停止")
        finally:
            # 线程结束时更新状态
            self.master.after(0, lambda: self.status_label.config(text="已停止"))

    def stop_clicker(self):
        self.exit_event.set()
        self.status_label.config(text="正在停止...")

    def on_f4_press(self, event):
        # 在热键回调中调度启动/停止（避免线程冲突）
        if self.clicker_thread and self.clicker_thread.is_alive():
            self.stop_clicker()
        else:
            self.start_clicker()

    # ---------- 异常处理 ----------
    def handle_exception(self, exception):
        try:
            with open("error_log.txt", "a", encoding='utf-8') as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {exception.__class__.__name__}: {exception}\n")
        except:
            pass

    # ---------- 窗口关闭 ----------
    def on_closing(self):
        self.stop_clicker()
        if self.clicker_thread and self.clicker_thread.is_alive():
            self.clicker_thread.join(timeout=1)
        self.master.destroy()


# ---------- 全局异常钩子 ----------
def global_exception_handler(exc_type, exc_value, exc_tb):
    try:
        with open("error_log.txt", "a", encoding='utf-8') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - GLOBAL: {exc_type.__name__}: {exc_value}\n")
    except:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

if __name__ == "__main__":
    sys.excepthook = global_exception_handler

    # 提示管理员权限（在Windows上）
    try:
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            tk.messagebox.showwarning("权限提示", "建议以管理员身份运行此程序，否则部分游戏可能无法响应点击。")
    except:
        pass

    root = tk.Tk()
    app = AutoclickerApp(root)
    root.mainloop()