import os
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, Toplevel
import datetime
import threading
import configparser
import shutil
import time

# ================== 更新日志 ==================
UPDATE_LOG = """
【使用说明】
1.由于个人水平有限，程序可能存在未发现的bug，如运行出现问题，请联系服务二部任巨晨；运行前建议前往github或找我获取最新版本
2.同时本人建议，将运维平台的sql文件执行功能单独拆分打包为可执行程序；不可否认运维工具功能全面，集成了部署升级、项目管理、操作留痕、身份验证等众多功能，但是单纯的部署和文件覆盖没必要使用运维平台，配置修改又用不了运维平台，用的最多的就是自动执行sql文件，但首次安装实在有些慢。
https://github.com/rjcren/some-tools/releases/tag/auto

【更新日志】
v0.1.0 (2026-04-22)
  在武凯 武总初始版本下借助AI二次开发
  - 添加错误文件转存功能
  - 将配置信息改为读取配置文件，打包程序为exe
v0.1.1 (2026-06-25)
  - 支持windows server 2008等老版本操作系统
v0.2.0 (2026-07-16)
  - 支持自定义连接字符串，用于仅能通过堡垒机连接的linux数据库服务器
  - 支持执行过程中停止(注意sql不会回滚)
  - 新增更新日志
  - 运行时指定变量 NLS_LANG 值
v0.3.0 (2026-07-23)
  - 优化PL/SQL块结束符添加逻辑
  - 单文件执行超时设置为30秒
  - 添加UTF-8文件无法无损转GBK时的自动判定：
    少量字符异常自动替换，超阈值自动暂停
  - 设置窗口增加“测试连接”按钮
"""
# ================== 默认配置 ==================
DEFAULT_CONFIG = {
    'Database': {
        'user': 'zcgl',
        'password': 'zcgl',
        'host': '10.3.3.121',
        'port': '1521',
        'service_name': 'shitan',
        'connection_string': ''
    },
    'Sqlplus': {
        'path': r'D:\app\A\product\11.2.0\dbhome_1\BIN\sqlplus.exe'
    }
}
CONFIG_FILE = 'autorunsql.ini'

def load_config():
    config = configparser.ConfigParser()
    modified = False
    if not os.path.exists(CONFIG_FILE):
        for section, options in DEFAULT_CONFIG.items():
            config[section] = options
        modified = True
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)
        messagebox.showinfo("提示", f"配置文件 {CONFIG_FILE} 已自动生成。")
    else:
        config.read(CONFIG_FILE, encoding='utf-8')
        for section, options in DEFAULT_CONFIG.items():
            if section not in config:
                config[section] = {}
                modified = True
            for key, value in options.items():
                if key not in config[section]:
                    config[section][key] = value
                    modified = True
        if modified:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
    for section, options in DEFAULT_CONFIG.items():
        if section not in config:
            config[section] = {}
        for key, value in options.items():
            if key not in config[section]:
                config[section][key] = value
    return config

# ================== SQL*Plus 执行器 ==================
class SQLPlusExecutor:
    MAX_AUTO_REPLACE_CHARS = 3   # 自动替换字符的阈值

    def __init__(self, db_config, sqlplus_path, log_callback=None):
        self.db_config = db_config
        self.sqlplus_path = sqlplus_path
        self.log_callback = log_callback
        self.connection_string = db_config.get('connection_string', '').strip()
        self.current_process = None
        self.stop_requested = False

        os.environ['NLS_LANG'] = 'AMERICAN_AMERICA.ZHS16GBK'
        self.log("已设置 NLS_LANG=AMERICAN_AMERICA.ZHS16GBK", "INFO")

    def log(self, message, level="INFO"):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        if self.log_callback:
            self.log_callback(log_line + "\n")

    @staticmethod
    def _count_unencodable_chars(text, encoding='gbk'):
        """统计字符串中无法用指定编码表示的字符数"""
        count = 0
        for ch in text:
            try:
                ch.encode(encoding)
            except UnicodeEncodeError:
                count += 1
        return count

    def ensure_plsql_slash(self, sql_content):
        """
        简单规则：若整个 SQL 内容的末尾有效部分是 END; 且后面没有单独的 '/'，
        则在末尾自动添加 '/'。不处理嵌套块和多个顶层块的情况。
        """
        stripped = sql_content.rstrip()
        lines = stripped.splitlines()
        while lines and lines[-1].strip().startswith('--'):
            lines.pop()
        if not lines:
            return sql_content
        last_line = lines[-1].rstrip()
        if re.match(r'.*\bEND\s*;\s*$', last_line, re.IGNORECASE):
            if not re.search(r'/\s*$', stripped, re.IGNORECASE):
                return sql_content.rstrip() + '\n/\n'
        return sql_content

    def stop(self):
        self.stop_requested = True
        if self.current_process and self.current_process.poll() is None:
            self.log("正在终止进程...", "WARNING")
            try:
                self.current_process.terminate()
                time.sleep(0.5)
                if self.current_process.poll() is None:
                    self.current_process.kill()
                self.log("进程已终止。", "WARNING")
            except Exception as e:
                self.log(f"终止进程出错: {e}", "ERROR")

    def _has_oracle_error(self, text):
        pattern = r'\b(ORA|SP2|PLS|SQL|TNS|EXP|IMP)-\d+'
        return bool(re.search(pattern, text, re.IGNORECASE))

    def execute_sql_file(self, file_path, show_command=False):
        if self.stop_requested:
            self.log("用户停止，跳过此文件。", "WARNING")
            return False

        if not os.path.exists(file_path):
            self.log(f"文件不存在: {file_path}", "ERROR")
            return False

        self.log(f"开始执行: {file_path}")

        # 读取文件
        content = None
        for enc in ['utf-8', 'gbk']:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            self.log(f"无法解码: {file_path}", "ERROR")
            return False

        # PL/SQL 块处理
        content_with_slash = self.ensure_plsql_slash(content)
        processed_content = "SET DEFINE OFF;\n" + content_with_slash
        if not processed_content.rstrip().endswith('EXIT'):
            processed_content += "\nEXIT;\n"

        # 编码检查：少量字符自动替换，超阈值直接失败
        encoding_errors = 'strict'
        try:
            processed_content.encode('gbk')
        except UnicodeEncodeError as e:
            bad_count = self._count_unencodable_chars(processed_content, 'gbk')
            if bad_count <= self.MAX_AUTO_REPLACE_CHARS:
                self.log(f"{bad_count} 个字符无法转换为 GBK，自动使用替换字符执行", "WARNING")
                encoding_errors = 'replace'
            else:
                self.log(f"文件包含 {bad_count} 个无法转换的字符，已跳过: {e}", "ERROR")
                return False

        # 构造连接字符串
        if self.connection_string:
            conn_str = self.connection_string
        else:
            conn_str = f"{self.db_config['user']}/{self.db_config['password']}@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['service_name']}"
        if not conn_str:
            self.log("连接字符串为空", "ERROR")
            return False

        cmd = f'"{self.sqlplus_path}" -S -L {conn_str}'
        if show_command:
            self.log(f"命令: {cmd}")

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding='gbk',
                errors=encoding_errors,
                shell=True,
                startupinfo=startupinfo
            )
            self.current_process = process
            try:
                stdout, stderr = process.communicate(input=processed_content, timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                self.log("执行超时（30秒）", "ERROR")
                return False
            retcode = process.returncode
            combined = stdout + stderr

            if self._has_oracle_error(combined):
                self.log(f"SQL 执行错误: {file_path}", "WARNING")
                if stdout.strip():
                    self.log(f"输出: {stdout.strip()}", "ERROR")
                if stderr.strip():
                    self.log(f"错误: {stderr.strip()}", "ERROR")
                return False

            if retcode == 0:
                self.log(f"成功: {file_path}")
                return True
            else:
                self.log(f"失败 (返回码 {retcode}): {file_path}", "ERROR")
                if stdout.strip():
                    self.log(f"输出: {stdout.strip()}", "ERROR")
                if stderr.strip():
                    self.log(f"错误: {stderr.strip()}", "ERROR")
                return False
        except Exception as e:
            self.log(f"执行异常: {e}", "ERROR")
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
            self.log(f"未找到 {extension} 文件", "WARNING")
            return False, []

        if sort_files:
            sql_files.sort()

        self.log(f"找到 {len(sql_files)} 个 SQL 文件")
        success_files = []
        failed_files = []

        for idx, file_path in enumerate(sql_files, 1):
            if self.stop_requested:
                self.log("用户停止，终止后续执行", "WARNING")
                break

            show_cmd = (idx == 1)
            success = self.execute_sql_file(file_path, show_command=show_cmd)

            if success:
                success_files.append(file_path)
            else:
                failed_files.append(file_path)

        self.log(f"批量完成：成功 {len(success_files)} 个，失败 {len(failed_files)} 个")
        if failed_files:
            self.log("失败列表：")
            for f in failed_files:
                self.log(f"  - {f}", "ERROR")
        return len(failed_files) == 0, failed_files

# ================== 设置窗口 ==================
class SettingsWindow:
    def __init__(self, parent, config, on_save_callback=None):
        self.parent = parent
        self.config = config
        self.on_save = on_save_callback
        self.window = Toplevel(parent)
        self.window.title("设置")
        self.window.geometry("450x520")
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

        tk.Label(self.window, text="连接字符串 (可选):").grid(row=row, column=0, padx=10, pady=2, sticky="e")
        self.conn_str_var = tk.StringVar(value=self.config['Database'].get('connection_string', ''))
        tk.Entry(self.window, textvariable=self.conn_str_var, width=30).grid(row=row, column=1, padx=10, pady=2, sticky="w")
        row += 1
        tk.Label(self.window, text="格式如：zcglv85/zcglv85@202.xxx.xxx.xxx_xxxxx_xxxxx；\n若填写则优先使用，并忽略host/port/service_name", fg="gray", font=("Arial", 10)).grid(
            row=row, column=0, columnspan=2, padx=10, pady=0, sticky="w")
        row += 1

        self.test_btn = tk.Button(self.window, text="测试连接", command=self.test_connection, bg="lightblue")
        self.test_btn.grid(row=row, column=0, columnspan=2, pady=5)
        row += 1

        tk.Label(self.window, text="SQL*Plus 设置", font=("Arial", 12, "bold")).grid(row=row, column=0, columnspan=2, pady=5, sticky="w")
        row += 1
        tk.Label(self.window, text="sqlplus 路径:").grid(row=row, column=0, padx=10, pady=2, sticky="e")
        self.sqlplus_path_var = tk.StringVar(value=self.config['Sqlplus'].get('path', ''))
        tk.Entry(self.window, textvariable=self.sqlplus_path_var, width=30).grid(row=row, column=1, padx=10, pady=2, sticky="w")
        tk.Button(self.window, text="浏览", command=self.browse_sqlplus).grid(row=row, column=2, padx=5)
        row += 1
        tk.Label(self.window, text="确保 sqlplus.exe 路径正确且可运行", fg="gray", font=("Arial", 10)).grid(
            row=row, column=0, columnspan=2, padx=10, pady=0, sticky="w")
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
        self.config['Database']['connection_string'] = self.conn_str_var.get().strip()
        self.config['Sqlplus']['path'] = self.sqlplus_path_var.get().strip()
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            self.config.write(f)
        if self.on_save:
            self.on_save(self.config)
        messagebox.showinfo("成功", "配置已保存并立即生效。")
        self.window.destroy()

    def test_connection(self):
        user = self.db_entries['user'].get().strip()
        password = self.db_entries['password'].get().strip()
        host = self.db_entries['host'].get().strip()
        port = self.db_entries['port'].get().strip()
        service_name = self.db_entries['service_name'].get().strip()
        conn_str_input = self.conn_str_var.get().strip()
        sqlplus_path = self.sqlplus_path_var.get().strip()

        if conn_str_input:
            conn_str = conn_str_input
        else:
            conn_str = f"{user}/{password}@{host}:{port}/{service_name}"

        if not conn_str or not sqlplus_path:
            messagebox.showwarning("警告", "请填写完整的连接信息和 SQL*Plus 路径")
            return

        self.test_btn.config(state=tk.DISABLED, text="测试中...")
        def do_test():
            try:
                cmd = f'"{sqlplus_path}" -S -L {conn_str}'
                test_sql = "SELECT 1 FROM DUAL;\nEXIT;\n"
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    encoding='gbk',
                    errors='replace',
                    shell=True
                )
                try:
                    stdout, stderr = proc.communicate(input=test_sql, timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate()
                    self.window.after(0, lambda: messagebox.showerror("连接失败", "连接超时（10秒）"))
                    return
                combined = stdout + stderr
                if proc.returncode == 0 and not re.search(r'\bORA-\d+', combined):
                    self.window.after(0, lambda: messagebox.showinfo("连接成功", "数据库连接测试成功！"))
                else:
                    err_msg = combined.strip() or "未知错误"
                    self.window.after(0, lambda: messagebox.showerror("连接失败", f"连接失败，错误信息：\n{err_msg}"))
            except Exception as e:
                self.window.after(0, lambda: messagebox.showerror("连接失败", f"测试过程出错：{e}"))
            finally:
                self.window.after(0, lambda: self.test_btn.config(state=tk.NORMAL, text="测试连接"))

        threading.Thread(target=do_test, daemon=True).start()

# ================== 主 GUI ==================
class Application:
    def __init__(self, root):
        self.root = root
        self.root.title("Oracle SQL 批量执行工具 v0.3.0 ")
        self.root.geometry("850x750")

        self.config = load_config()
        self.db_config = dict(self.config['Database'])
        self.sqlplus_path = self.config['Sqlplus']['path']

        self.executor = None
        self.running = False

        # GUI 控件
        frame_top = tk.Frame(root)
        frame_top.pack(pady=10, fill=tk.X)

        tk.Label(frame_top, text="选择要执行的SQL文件或文件夹：").pack(side=tk.LEFT, padx=5)
        self.path_var = tk.StringVar()
        tk.Entry(frame_top, textvariable=self.path_var, width=50).pack(side=tk.LEFT, padx=5)
        tk.Button(frame_top, text="浏览文件", command=self.select_file).pack(side=tk.LEFT, padx=2)
        tk.Button(frame_top, text="浏览文件夹", command=self.select_folder).pack(side=tk.LEFT, padx=2)
        tk.Button(frame_top, text="设置", command=self.open_settings, bg="lightblue").pack(side=tk.LEFT, padx=10)
        tk.Button(frame_top, text="更新日志", command=self.show_update_log, bg="lightyellow").pack(side=tk.LEFT, padx=5)

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
        self.start_button = tk.Button(frame_mid, text="开始执行", command=self.start_execution, bg="lightgreen", width=12)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = tk.Button(frame_mid, text="停止", command=self.stop_execution, bg="lightcoral", width=12, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        tk.Button(frame_mid, text="清空日志", command=self.clear_log, width=12).pack(side=tk.LEFT, padx=5)

        tk.Label(root, text="执行日志：").pack(anchor=tk.W, padx=10)
        self.log_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Consolas", 9))
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        tk.Label(root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

        self.reload_executor()

    def reload_executor(self):
        self.executor = SQLPlusExecutor(
            self.db_config,
            self.sqlplus_path,
            log_callback=self.append_log
        )

    def on_settings_saved(self, config):
        self.config = config
        self.db_config = dict(config['Database'])
        self.sqlplus_path = config['Sqlplus']['path']
        self.reload_executor()
        self.append_log("配置已更新并生效。\n")

    def show_update_log(self):
        win = Toplevel(self.root)
        win.title("更新日志")
        win.geometry("600x400")
        text_area = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Consolas", 12))
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_area.insert(tk.END, UPDATE_LOG)
        text_area.config(state=tk.DISABLED)

    def select_file(self):
        path = filedialog.askopenfilename(filetypes=[("SQL files", "*.sql"), ("All files", "*.*")])
        if path:
            self.path_var.set(path)

    def select_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.path_var.set(path)

    def open_settings(self):
        if self.running:
            messagebox.showwarning("警告", "请等待任务执行完毕后再修改设置。")
            return
        SettingsWindow(self.root, self.config, on_save_callback=self.on_settings_saved)

    def toggle_copy_dir(self):
        state = tk.NORMAL if self.copy_failed_enabled.get() else tk.DISABLED
        self.copy_dir_entry.config(state=state)
        self.browse_copy_btn.config(state=state)

    def browse_copy_dir(self):
        path = filedialog.askdirectory(title="选择存放失败文件的文件夹")
        if path:
            self.copy_dir_var.set(path)

    def append_log(self, text):
        def do_append():
            self.log_area.insert(tk.END, text)
            self.log_area.see(tk.END)
            self.root.update_idletasks()
        self.root.after(0, do_append)

    def clear_log(self):
        self.log_area.delete(1.0, tk.END)

    def update_status(self, text):
        self.root.after(0, lambda: self.status_var.set(text))

    def stop_execution(self):
        if self.running and self.executor:
            self.append_log("\n用户请求停止任务...\n")
            self.executor.stop()
            self.stop_button.config(state=tk.DISABLED)
            self.update_status("正在停止...")

    def copy_failed_files(self, failed_files, source_root):
        if not failed_files:
            return
        target_root = self.copy_dir_var.get().strip()
        if not target_root:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            target_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"failed_{timestamp}")
            self.append_log(f"未指定目录，自动创建: {target_root}\n")
        os.makedirs(target_root, exist_ok=True)
        copied = 0
        for f in failed_files:
            if os.path.isfile(source_root):
                rel = os.path.basename(f)
            else:
                rel = os.path.relpath(f, source_root)
            dest = os.path.join(target_root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                shutil.copy2(f, dest)
                copied += 1
                self.append_log(f"已复制: {rel} -> {dest}\n")
            except Exception as e:
                self.append_log(f"复制失败 {f}: {e}\n")
        self.append_log(f"共复制 {copied} 个失败文件到 {target_root}\n")

    def start_execution(self):
        target = self.path_var.get().strip()
        if not target:
            messagebox.showwarning("警告", "请选择要执行的路径")
            return
        if not os.path.exists(target):
            messagebox.showerror("错误", f"路径不存在：{target}")
            return
        if self.running:
            messagebox.showinfo("提示", "任务正在执行中")
            return

        try:
            self.config.read(CONFIG_FILE, encoding='utf-8')
            self.db_config = dict(self.config['Database'])
            self.sqlplus_path = self.config['Sqlplus']['path']
            self.reload_executor()
        except Exception as e:
            self.append_log(f"读取配置出错: {e}\n")
            return

        def run():
            self.running = True
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.update_status("正在执行...")
            failed_files = []
            success = False
            try:
                if os.path.isfile(target):
                    success = self.executor.execute_sql_file(target, show_command=True)
                    if not success:
                        failed_files = [target]
                    self.append_log("\n执行成功。\n" if success else "\n执行失败。\n")
                else:
                    success, failed_files = self.executor.execute_folder(target, sort_files=True)
                    if success:
                        self.append_log("\n全部执行完毕。\n")
                    else:
                        self.append_log(f"\n共 {len(failed_files)} 个文件失败。\n")
            except Exception as e:
                self.append_log(f"\n异常: {e}\n")
                self.update_status("执行出错")
            finally:
                if self.copy_failed_enabled.get() and failed_files:
                    self.append_log("\n复制失败文件...\n")
                    self.copy_failed_files(failed_files, target)
                self.running = False
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED)
                if self.executor:
                    self.executor.stop_requested = False
                self.update_status("完成" if success else "失败")

        threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = Application(root)
    root.mainloop()