import tkinter as tk
import tkinter.ttk as ttk
import tkinter.messagebox
import time
from threading import Thread, Event
import keyboard
import sys
import pyautogui

class AutoclickerApp:
    def __init__(self, master):

        self.master = master
        self.master.title("自动点击器 - 按 F4 启停")
        self.master.geometry("330x100")

        self.top_frame = ttk.Frame(self.master, width=310, height=50)
        self.top_frame.place(x=10, y=10)
        # 毫秒输入框
        self.milliseconds_label = ttk.Label(self.top_frame, text="毫秒:")
        self.milliseconds_label.place(relx=0.05, rely=0)
        self.milliseconds_entry = ttk.Entry(self.top_frame)
        self.milliseconds_entry.place(relx=0.2, rely=0, relwidth=0.25)
        # 连点按键
        self.select_key_label = ttk.Label(self.top_frame, text="按键:")
        self.select_key_label.place(relx=0.5, rely=0)
        volues = ["左键", "右键", "中键"]
        self.select_key_entry = ttk.Combobox(self.top_frame, values=volues, width=5)
        self.select_key_entry.current(0)
        self.select_key_entry.place(relx=0.65, rely=0, relwidth=0.25)

        self.end_frame = ttk.Frame(self.master, width=310, height=50)
        self.end_frame.place(x=10, y=50)
        # 开始和停止按钮
        self.start_button = ttk.Button(self.end_frame, text="开始", command=self.start_clicker)
        self.start_button.place(relx=0.15, rely=0, relwidth=0.3)
        self.stop_button = ttk.Button(self.end_frame, text="停止", command=self.stop_clicker)
        self.stop_button.place(relx=0.55, rely=0, relwidth=0.3)

        self.top_frame.lift()
        self.end_frame.lift()
        self.clicker_thread = None
        self.exit_event = Event()
        keyboard.on_press_key("F4", self.on_f4_press)

    def start_clicker(self):
        try:
            milliseconds = int(self.milliseconds_entry.get())
            if milliseconds < 50 :
                tk.messagebox.showwarning("错误", "间隔必须大于50毫秒")
                return
        except ValueError:
            tk.messagebox.showwarning("错误", "请输入有效的秒和毫秒")
            return
        # 启动连点器线程
        if not self.clicker_thread or not self.clicker_thread.is_alive():
            self.exit_event.clear()
            self.clicker_thread = Thread(target=self.run_clicker, args=(milliseconds,))
            self.clicker_thread.start()

    def run_clicker(self, total_milliseconds):
        click_key = self.select_key_entry.get()
        try:
            while not self.exit_event.is_set():
                time.sleep(total_milliseconds / 1000)
                screenWidth, screenHeight = pyautogui.size()
                x, y = pyautogui.position()
                if click_key == "左键":
                    pyautogui.click(button="left")
                elif click_key == "右键":
                    pyautogui.click(button="right")
                elif click_key == "中键":
                    pyautogui.click(button="middle")
        except Exception as e:
            self.handle_exception(e)

    def stop_clicker(self):
        self.exit_event.set()

    def on_f4_press(self, event):
        if self.clicker_thread and self.clicker_thread.is_alive():
            self.stop_clicker()
        else:
            self.start_clicker()

    def handle_exception(self, exception):
        try:
            with open("error_log.txt", "a") as f:
                f.write(f"{ time.strftime('%Y-%m-%d %H:%M:%S：', time.localtime()) + str(exception.__class__.__name__) + ': '+ str(exception)}\n")
        except Exception as e:
            print(f"写入异常信息到文件时出错: {e}")

if __name__ == "__main__":
    sys.excepthook = lambda value: AutoclickerApp(None).handle_exception(value)
    root = tk.Tk()
    app = AutoclickerApp(root)
    root.mainloop()
