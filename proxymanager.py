import os
import subprocess
import json
import tkinter as tk
from tkinter import messagebox, simpledialog
import ctypes
import sys

# 检查是否以管理员权限运行
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

# 请求管理员权限
def request_admin():
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()

# 请求管理员权限
request_admin()

# 预设代理配置文件路径
CONFIG_FILE = "proxy_presets.json"

# 默认预设代理
DEFAULT_PRESETS = [
    {"name": "http_proxy1", "type": "http", "address": "127.0.0.1:8080"},
    {"name": "socks_proxy1", "type": "socks", "address": "127.0.0.1:1080"},
]

class ProxyManager:
    """
    代理管理类
    """
    @staticmethod
    def load_presets():
        """
        加载预设代理
        """
        if not os.path.exists(CONFIG_FILE):
            # 如果配置文件不存在，创建并写入默认预设
            with open(CONFIG_FILE, "w") as f:
                json.dump(DEFAULT_PRESETS, f, indent=4)
            return DEFAULT_PRESETS
        else:
            # 如果配置文件存在，读取预设
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)

    @staticmethod
    def save_presets(presets):
        """
        保存预设代理
        """
        with open(CONFIG_FILE, "w") as f:
            json.dump(presets, f, indent=4)

    @staticmethod
    def set_proxy(proxy_type, proxy_address):
        """
        设置系统代理
        """
        try:
            if proxy_type == "http":
                # 设置 HTTP/HTTPS 代理
                os.environ["HTTP_PROXY"] = f"http://{proxy_address}"
                os.environ["HTTPS_PROXY"] = f"http://{proxy_address}"
                subprocess.run(f"netsh winhttp set proxy {proxy_address}", shell=True, check=True)
                messagebox.showinfo("成功", f"已设置 HTTP/HTTPS 代理为: http://{proxy_address}")

            elif proxy_type == "socks":
                # 设置 SOCKS 代理
                os.environ["HTTP_PROXY"] = f"socks5://{proxy_address}"
                os.environ["HTTPS_PROXY"] = f"socks5://{proxy_address}"
                messagebox.showinfo("成功", f"已设置 SOCKS 代理为: socks5://{proxy_address}")

        except Exception as e:
            messagebox.showerror("错误", f"设置代理时出错: {e}")

    @staticmethod
    def clear_proxy():
        """
        清除系统代理
        """
        try:
            # 清除环境变量
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
            subprocess.run("netsh winhttp reset proxy", shell=True, check=True)
            messagebox.showinfo("成功", "已清除系统代理设置。")

        except Exception as e:
            messagebox.showerror("错误", f"清除代理时出错: {e}")

class ProxyManagerApp:
    """
    GUI 应用程序
    """
    def __init__(self, root):
        self.root = root
        self.root.title("代理管理器")
        self.presets = ProxyManager.load_presets()

        # 创建 GUI 组件
        self.create_widgets()

    def create_widgets(self):
        """
        创建 GUI 组件
        """
        # 预设代理列表
        self.preset_listbox = tk.Listbox(self.root, width=50, height=10)
        self.preset_listbox.pack(pady=10)
        self.update_preset_list()

        # 按钮框架
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=10)

        tk.Button(button_frame, text="添加代理", command=self.show_add_dialog).grid(row=0, column=0, padx=5)
        tk.Button(button_frame, text="编辑代理", command=self.show_edit_dialog).grid(row=0, column=1, padx=5)
        tk.Button(button_frame, text="删除代理", command=self.delete_preset).grid(row=0, column=2, padx=5)
        tk.Button(button_frame, text="设置代理", command=self.set_proxy_from_preset).grid(row=0, column=3, padx=5)
        tk.Button(button_frame, text="清除代理", command=ProxyManager.clear_proxy).grid(row=0, column=4, padx=5)

    def update_preset_list(self):
        """
        更新预设代理列表
        """
        self.preset_listbox.delete(0, tk.END)
        for proxy in self.presets:
            self.preset_listbox.insert(tk.END, f"{proxy['name']} ({proxy['type']}): {proxy['address']}")

    def show_add_dialog(self):
        """
        显示添加代理对话框
        """
        self.show_proxy_dialog("添加代理", self.add_preset)

    def show_edit_dialog(self):
        """
        显示编辑代理对话框
        """
        selected = self.preset_listbox.curselection()
        if not selected:
            messagebox.showerror("错误", "请选择一个代理。")
            return

        # 获取选中的代理
        selected_proxy = self.presets[selected[0]]
        self.show_proxy_dialog("编辑代理", self.edit_preset, selected_proxy)

    def show_proxy_dialog(self, title, confirm_callback, proxy=None):
        """
        显示代理对话框（添加/编辑）
        """
        dialog = tk.Toplevel(self.root)
        dialog.title(title)

        # 代理名称输入框
        tk.Label(dialog, text="代理名称:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        name_entry = tk.Entry(dialog, width=25)
        name_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        if proxy:
            name_entry.insert(0, proxy["name"])
        name_entry.focus_set()  # 自动聚焦到名称输入框

        # 代理类型选择
        tk.Label(dialog, text="代理类型:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        proxy_type_frame = tk.Frame(dialog)
        proxy_type_frame.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        proxy_type_var = tk.StringVar(value=proxy["type"] if proxy else "http")
        tk.Radiobutton(proxy_type_frame, text="HTTP", variable=proxy_type_var, value="http").pack(side="left", padx=5)
        tk.Radiobutton(proxy_type_frame, text="SOCKS", variable=proxy_type_var, value="socks").pack(side="left", padx=5)

        # 代理地址输入框
        tk.Label(dialog, text="代理地址 (ip:port):").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        address_entry = tk.Entry(dialog, width=25)
        address_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        if proxy:
            address_entry.insert(0, proxy["address"])

        # 确认按钮
        def confirm():
            name = name_entry.get()
            proxy_type = proxy_type_var.get()
            address = address_entry.get()
            if not name or not address:
                messagebox.showerror("错误", "代理名称和地址不能为空。")
                return

            confirm_callback(name, proxy_type, address, proxy)
            dialog.destroy()

        tk.Button(dialog, text="确认", command=confirm).grid(row=3, column=0, columnspan=2, pady=10)

    def add_preset(self, name, proxy_type, address, _):
        """
        添加预设代理
        """
        # 检查名称是否已存在
        if any(proxy["name"] == name for proxy in self.presets):
            messagebox.showerror("错误", f"预设代理 '{name}' 已存在。")
            return

        # 添加新代理
        self.presets.append({"name": name, "type": proxy_type, "address": address})
        ProxyManager.save_presets(self.presets)
        self.update_preset_list()
        messagebox.showinfo("成功", f"已添加预设代理 '{name}'。")

    def edit_preset(self, new_name, proxy_type, address, selected_proxy):
        """
        编辑预设代理
        """
        # 检查名称是否已存在（排除自身）
        if any(proxy["name"] == new_name for proxy in self.presets if proxy["name"] != selected_proxy["name"]):
            messagebox.showerror("错误", f"预设代理 '{new_name}' 已存在。")
            return

        # 更新代理配置
        selected_proxy["name"] = new_name
        selected_proxy["type"] = proxy_type
        selected_proxy["address"] = address
        ProxyManager.save_presets(self.presets)
        self.update_preset_list()
        messagebox.showinfo("成功", f"已更新预设代理 '{new_name}'。")

    def delete_preset(self):
        """
        删除预设代理
        """
        selected = self.preset_listbox.curselection()
        if not selected:
            messagebox.showerror("错误", "请选择一个代理。")
            return

        # 获取选中的代理名称
        selected_proxy = self.presets[selected[0]]
        proxy_name = selected_proxy["name"]

        # 确认删除
        confirm = messagebox.askyesno("确认删除", f"确定要删除代理 '{proxy_name}' 吗？")
        if not confirm:
            return

        # 删除代理
        self.presets.pop(selected[0])
        ProxyManager.save_presets(self.presets)
        self.update_preset_list()
        messagebox.showinfo("成功", f"已删除预设代理 '{proxy_name}'。")

    def set_proxy_from_preset(self):
        """
        从预设代理设置系统代理
        """
        selected = self.preset_listbox.curselection()
        if not selected:
            messagebox.showerror("错误", "请选择一个代理。")
            return

        # 获取选中的代理
        selected_proxy = self.presets[selected[0]]
        proxy_type = selected_proxy["type"]
        proxy_address = selected_proxy["address"]
        ProxyManager.set_proxy(proxy_type, proxy_address)

if __name__ == "__main__":
    # 创建主窗口
    root = tk.Tk()
    app = ProxyManagerApp(root)
    root.mainloop()