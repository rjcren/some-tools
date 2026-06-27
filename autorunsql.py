import os
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, Toplevel
import datetime
import threading
import configparser
import shutil

# ================== 默认配置（首次运行自动生成 config.ini） ==================
DEFAULT_CONFIG = {
    'Database': {
        'user': 'zcgl',
        'password': 'zcgl',
        'host': '10.3.3.121',
        'port': '1521',
        'service_name': 'shitan'
    },
    'Sqlplus': {
        'path': r'D:\app\wukai\product\11.2.0\dbhome_1\BIN\sqlplus.exe'
    }
}
CONFIG_FILE = 'config.ini'

def load_config():
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE):
        for section, options in DEFAULT_CONFIG.items():
            config[section] = options
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)
        messagebox.showinfo("提示", f"配置文件 {CONFIG_FILE} 不存在，已自动生成默认配置，请根据需要修改后重新运行程序。")
    else:
        config.read(CONFIG_FILE, encoding='utf-8')
    for section, options in DEFAULT_CONFIG.items():
        if section not in config:
            config[section] = {}
        for key, value in options.items():
            if key not in config[section]:
                config[section][key] = value
    return config

# ================== SQL*Plus 执行器 ==================
class SQLPlusExecutor:
    def __init__(self, db_config, sqlplus_path, log_callback=None):
        self.db_config = db_config
        self.sqlplus_path = sqlplus_path
        self.log_callback = log_callback
        self.command_printed = False

    def log(self, message, level="INFO"):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        if self.log_callback:
            self.log_callback(log_line + "\n")

    def add_slash_to_plsql_blocks(self, sql_content):
        pattern = r'(?s)((?:(?:DECLARE\s+)?BEGIN\s+.*?END\s*;))\s*(?!/)'
        def replacer(match):
            return match.group(1) + '\n/\n'
        return re.sub(pattern, replacer, sql_content, flags=re.IGNORECASE)

    def execute_sql_file(self, file_path, show_command=False):
        if not os.path.exists(file_path):
            self.log(f"文件不存在: {file_path}", "ERROR")
            return False

        self.log(f"开始执行文件: {file_path}")

        content = None
        for enc in ['utf-8', 'gbk']:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            self.log(f"无法解码文件: {file_path}", "ERROR")
            return False

        processed_content = self.add_slash_to_plsql_blocks(content)
        if not processed_content.rstrip().endswith('EXIT'):
            processed_content += "\nEXIT;\n"

        conn_str = f"{self.db_config['user']}/{self.db_config['password']}@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['service_name']}"
        cmd = f'"{self.sqlplus_path}" -S -L {conn_str}'

        if show_command:
            self.log(f"执行命令: {cmd}")

        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding='gbk',
                errors='replace',
                shell=True,
                startupinfo=startupinfo
            )

            stdout, stderr = process.communicate(input=processed_content, timeout=3600)
            stdout = stdout or ""
            stderr = stderr or ""

            if process.returncode == 0:
                combined = stdout + stderr
                if "ERROR" in combined.upper() or "ORA-" in combined.upper():
                    self.log(f"⚠️ 文件执行完成但存在 SQL 错误: {file_path}", "WARNING")
                    return False
                else:
                    self.log(f"✅ 文件执行成功: {file_path}")
                    return True
            else:
                self.log(f"❌ sqlplus 执行失败 (返回码 {process.returncode}): {file_path}", "ERROR")
                if stdout.strip():
                    self.log(f"输出: {stdout.strip()}", "ERROR")
                if stderr.strip():
                    self.log(f"错误: {stderr.strip()}", "ERROR")
                return False
        except subprocess.TimeoutExpired:
            process.kill()
            self.log(f"❌ 执行超时: {file_path}", "ERROR")
            return False
        except Exception as e:
            self.log(f"❌ 调用 sqlplus 异常: {file_path} - {e}", "ERROR")
            return False

    def execute_folder(self, folder_path, extension=".sql", sort_files=True):
        if not os.path.isdir(folder_path):
            self.log(f"文件夹不存在: {folder_path}", "ERROR")
            return False, []

        sql_files = []
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(extension.lower()):
                    sql_files.append(os.path.join(root, file))

        if not sql_files:
            self.log(f"文件夹中没有找到 {extension} 文件", "WARNING")
            return False, []

        if sort_files:
            sql_files.sort()

        self.log(f"找到 {len(sql_files)} 个 SQL 文件，开始批量执行...")
        success_files = []
        failed_files = []
        self.command_printed = False

        for idx, file_path in enumerate(sql_files, 1):
            show_cmd = (idx == 1)
            if self.execute_sql_file(file_path, show_command=show_cmd):
                success_files.append(file_path)
            else:
                failed_files.append(file_path)

        self.log(f"批量执行完成：共 {len(sql_files)} 个文件，成功 {len(success_files)} 个，失败 {len(failed_files)} 个")
        if failed_files:
            self.log("失败的文件列表：")
            for f in failed_files:
                self.log(f"  - {f}", "ERROR")
        return len(failed_files) == 0, failed_files

# ================== 设置窗口 ==================
class SettingsWindow:
    def __init__(self, parent, config):
        self.parent = parent
        self.config = config
        self.window = Toplevel(parent)
        self.window.title("设置")
        self.window.geometry("450x400")
        self.window.resizable(False, False)

        tk.Label(self.window, text="数据库配置", font=("Arial", 12, "bold")).grid(row=0, column=0, columnspan=2, pady=5, sticky="w")
        row = 1
        self.db_entries = {}
        for key in ['user', 'password', 'host', 'port', 'service_name']:
            tk.Label(self.window, text=key + ":").grid(row=row, column=0, padx=10, pady=2, sticky="e")
            entry = tk.Entry(self.window, width=30)
            entry.insert(0, self.config['Database'].get(key, ''))
            entry.grid(row=row, column=1, padx=10, pady=2, sticky="w")
            self.db_entries[key] = entry
            row += 1

        tk.Label(self.window, text="SQL*Plus 设置", font=("Arial", 12, "bold")).grid(row=row, column=0, columnspan=2, pady=5, sticky="w")
        row += 1
        tk.Label(self.window, text="sqlplus 路径:").grid(row=row, column=0, padx=10, pady=2, sticky="e")
        self.sqlplus_path_var = tk.StringVar(value=self.config['Sqlplus'].get('path', ''))
        entry_sqlplus = tk.Entry(self.window, textvariable=self.sqlplus_path_var, width=30)
        entry_sqlplus.grid(row=row, column=1, padx=10, pady=2, sticky="w")
        tk.Button(self.window, text="浏览", command=self.browse_sqlplus).grid(row=row, column=2, padx=5)

        row += 1
        tk.Button(self.window, text="保存", command=self.save_settings, width=10).grid(row=row, column=0, pady=20)
        tk.Button(self.window, text="取消", command=self.window.destroy, width=10).grid(row=row, column=1, pady=20)

    def browse_sqlplus(self):
        path = filedialog.askopenfilename(title="选择 sqlplus.exe", filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if path:
            self.sqlplus_path_var.set(path)

    def save_settings(self):
        for key, entry in self.db_entries.items():
            self.config['Database'][key] = entry.get().strip()
        self.config['Sqlplus']['path'] = self.sqlplus_path_var.get().strip()
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            self.config.write(f)
        messagebox.showinfo("成功", "配置已保存，请重启程序使配置生效。")
        self.window.destroy()

# ================== 主 GUI 界面 ==================
class Application:
    def __init__(self, root):
        self.root = root
        self.root.title("Oracle SQL 批量执行工具 (SQL*Plus)")
        self.root.geometry("850x750")

        self.config = load_config()
        self.db_config = dict(self.config['Database'])
        self.sqlplus_path = self.config['Sqlplus']['path']

        self.executor = SQLPlusExecutor(self.db_config, self.sqlplus_path, log_callback=self.append_log)
        self.running = False

        # 界面控件
        frame_top = tk.Frame(root)
        frame_top.pack(pady=10)

        tk.Label(frame_top, text="选择要执行的SQL文件或文件夹：").pack(side=tk.LEFT, padx=5)
        self.path_var = tk.StringVar()
        tk.Entry(frame_top, textvariable=self.path_var, width=50).pack(side=tk.LEFT, padx=5)
        tk.Button(frame_top, text="浏览文件", command=self.select_file).pack(side=tk.LEFT, padx=2)
        tk.Button(frame_top, text="浏览文件夹", command=self.select_folder).pack(side=tk.LEFT, padx=2)
        tk.Button(frame_top, text="设置", command=self.open_settings, bg="lightblue").pack(side=tk.LEFT, padx=10)

        # 复制失败文件选项
        frame_copy = tk.Frame(root)
        frame_copy.pack(pady=5, fill=tk.X, padx=10)
        self.copy_failed_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(frame_copy, text="复制失败文件到目录", variable=self.copy_failed_enabled, command=self.toggle_copy_dir).pack(side=tk.LEFT, padx=5)
        self.copy_dir_var = tk.StringVar()
        self.copy_dir_entry = tk.Entry(frame_copy, textvariable=self.copy_dir_var, width=40, state=tk.DISABLED)
        self.copy_dir_entry.pack(side=tk.LEFT, padx=5)
        self.browse_copy_btn = tk.Button(frame_copy, text="浏览", command=self.browse_copy_dir, state=tk.DISABLED)
        self.browse_copy_btn.pack(side=tk.LEFT, padx=2)

        frame_mid = tk.Frame(root)
        frame_mid.pack(pady=5)
        self.start_button = tk.Button(frame_mid, text="开始执行", command=self.start_execution, bg="lightgreen", width=15)
        self.start_button.pack(side=tk.LEFT, padx=10)
        tk.Button(frame_mid, text="清空日志", command=self.clear_log, width=15).pack(side=tk.LEFT, padx=10)

        tk.Label(root, text="执行日志：").pack(anchor=tk.W, padx=10)
        self.log_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Consolas", 9))
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        tk.Label(root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

    def select_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("SQL files", "*.sql"), ("All files", "*.*")])
        if file_path:
            self.path_var.set(file_path)

    def select_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.path_var.set(folder_path)

    def open_settings(self):
        if self.running:
            messagebox.showwarning("警告", "请等待当前任务执行完毕后再修改设置。")
            return
        SettingsWindow(self.root, self.config)

    def toggle_copy_dir(self):
        state = tk.NORMAL if self.copy_failed_enabled.get() else tk.DISABLED
        self.copy_dir_entry.config(state=state)
        self.browse_copy_btn.config(state=state)

    def browse_copy_dir(self):
        dir_path = filedialog.askdirectory(title="选择存放失败文件的文件夹")
        if dir_path:
            self.copy_dir_var.set(dir_path)

    def append_log(self, text):
        def do_append():
            self.log_area.insert(tk.END, text)
            self.log_area.see(tk.END)
            self.root.update_idletasks()
        self.root.after(0, do_append)

    def clear_log(self):
        self.log_area.delete(1.0, tk.END)

    def update_status(self, text):
        self.status_var.set(text)
        self.root.update_idletasks()

    def copy_failed_files(self, failed_files, source_root):
        """
        将失败文件复制到目标目录，保持相对路径结构。
        source_root: 输入的根目录（如果是单文件，则为该文件所在目录）
        """
        if not failed_files:
            return
        # 确定目标根目录
        target_root = self.copy_dir_var.get().strip()
        if not target_root:
            # 自动生成带时间戳的文件夹
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            target_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"failed_{timestamp}")
            self.append_log(f"未指定目标目录，自动创建: {target_root}\n")
        os.makedirs(target_root, exist_ok=True)

        copied_count = 0
        for file_path in failed_files:
            # 计算相对路径
            if os.path.isfile(source_root):
                # 单文件模式，直接复制文件到目标根目录，不保留额外路径
                rel_path = os.path.basename(file_path)
            else:
                # 文件夹模式，保持相对于 source_root 的路径
                rel_path = os.path.relpath(file_path, source_root)
            dest_path = os.path.join(target_root, rel_path)
            dest_dir = os.path.dirname(dest_path)
            os.makedirs(dest_dir, exist_ok=True)
            try:
                shutil.copy2(file_path, dest_path)
                copied_count += 1
                self.append_log(f"已复制失败文件: {rel_path} -> {dest_path}\n")
            except Exception as e:
                self.append_log(f"复制失败 {file_path}: {e}\n", "ERROR")
        self.append_log(f"共复制 {copied_count} 个失败文件到目录: {target_root}\n")

    def start_execution(self):
        target_path = self.path_var.get().strip()
        if not target_path:
            messagebox.showwarning("警告", "请选择或输入要执行的SQL文件/文件夹路径")
            return
        if not os.path.exists(target_path):
            messagebox.showerror("错误", f"路径不存在：{target_path}")
            return
        if self.running:
            messagebox.showinfo("提示", "任务正在执行中，请稍后")
            return

        # 重新加载配置
        try:
            self.config.read(CONFIG_FILE, encoding='utf-8')
            self.db_config = dict(self.config['Database'])
            self.sqlplus_path = self.config['Sqlplus']['path']
            self.executor = SQLPlusExecutor(self.db_config, self.sqlplus_path, log_callback=self.append_log)
        except Exception as e:
            self.append_log(f"读取配置文件出错: {e}\n")
            return

        def run():
            self.running = True
            self.start_button.config(state=tk.DISABLED)
            self.update_status("正在执行...")
            failed_files = []
            success = False
            try:
                if os.path.isfile(target_path):
                    success = self.executor.execute_sql_file(target_path, show_command=True)
                    if not success:
                        failed_files = [target_path]
                    if success:
                        self.append_log("\n✅ 文件执行成功。\n")
                        self.update_status("执行完成")
                    else:
                        self.append_log("\n⚠️ 文件执行失败。\n")
                        self.update_status("执行失败")
                else:
                    success, failed_files = self.executor.execute_folder(target_path, sort_files=True)
                    if success:
                        self.append_log("\n✅ 所有任务执行完毕。\n")
                        self.update_status("执行完成")
                    else:
                        self.append_log(f"\n⚠️ 共 {len(failed_files)} 个文件执行失败，详情见日志。\n")
                        self.update_status("执行完成（存在失败）")
            except Exception as e:
                self.append_log(f"\n❌ 执行过程中发生异常: {e}\n")
                self.update_status("执行出错")
            finally:
                # 复制失败文件
                if self.copy_failed_enabled.get() and failed_files:
                    self.append_log("\n开始复制失败文件...\n")
                    self.copy_failed_files(failed_files, target_path)
                self.running = False
                self.start_button.config(state=tk.NORMAL)

        threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = Application(root)
    root.mainloop()