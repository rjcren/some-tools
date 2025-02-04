import tkinter as tk
from tkinter import messagebox
import random

def move_disagree_button(event=None):
    x = random.randint(0, window.winfo_width() - 100)
    y = random.randint(0, window.winfo_height() - 30)
    disagree_button.place(x=x, y=y)

def agree():
    agree_label.config(text="测试成功！")
    disagree_button.place_forget()
    window.protocol("WM_DELETE_WINDOW", window.destroy)

def disagree():
    move_disagree_button()

def on_closing():
    if agree_label.cget("text") == "":
        tk.messagebox.showwarning("要同意", "不同意关不了哦亲")
    else:
        window.destroy()

window = tk.Tk()
window.title("测试程序")
window.geometry("400x300")

agree_button = tk.Button(window, text="同意", width=10, command=agree)
agree_button.pack(pady=10)

disagree_button = tk.Button(window, text="不同意", width=10, command=disagree)
disagree_button.pack(pady=10)

agree_label = tk.Label(window, text="")
agree_label.pack(pady=10)

disagree_button.bind("<Enter>", move_disagree_button)
window.protocol("WM_DELETE_WINDOW", on_closing)

window.mainloop()