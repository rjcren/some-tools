import os
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, Toplevel
import datetime
import threading
import configparser
import shutil
import sys
import queue
import time
import json

# ================== 使用说明 ==================
UPDATE_LOG = """
【观前提示】
注：此前版本全部作废
由于个人水平有限，程序可能存在未发现的bug，如运行出现问题，请联系服务二部任巨晨；运行前建议前往github或找我获取最新版本
https://github.com/rjcren/some-tools/releases/tag/auto

【使用教程】
1. 点击【设置】，填写数据库连接信息与 sqlplus.exe 路径，点【测试连接】确认可用；
2. 选择要执行的 SQL 文件或文件夹（文件夹会递归查找所有 .sql 文件并按名称排序执行）；
3. 如需失败转存，勾选【复制失败文件到目录】并指定目录；
4. 点击【开始执行】，执行过程中可点【停止】（注意：已执行的 SQL 不会回滚）。
   单文件执行没有固定超时，长时间任务可通过【停止】主动中断。

配置文件保存在当前用户的 AppData 目录中

【构建信息】
Python 版本：3.6.8（不可使用新版本，会导致ws2008兼容性问题）
打包工具：PyInstaller 4.10
打包钩子库：pyinstaller-hooks-contrib 2022.0

【更新日志】
v0.1.0 (2026-04-22)
  在武凯武总初始版本下借助AI二次开发
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
  - 添加UTF-8文件无法无损转GBK时的自动判定：
    少量字符异常自动替换，超阈值自动暂停
  - 设置窗口增加“测试连接”按钮
v0.3.1 (2026-10-30)
  - 优化设置窗口体验，增加自动获取sqlplus路径功能，优化窗口显示逻辑
  - 支持弱口令整改后的数据库密码
  - 配置文件迁移至用户目录
"""
# ================== 默认配置 ==================
DEFAULT_CONFIG = {
    'Database': {
        'user': '',
        'password': '',
        'host': '10.3.3.121',
        'port': '1521',
        'service_name': 'shitan',
        'connection_string': ''
    },
    'Sqlplus': {
        'path': r'D:\app\A\product\11.2.0\dbhome_1\BIN\sqlplus.exe'
    }
}
APP_DATA_DIR = os.path.join(
    os.environ.get('APPDATA') or os.path.expanduser('~'),
    'AutoRunSQL'
)
CONFIG_FILE = os.path.join(APP_DATA_DIR, 'autorunsql.ini')

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


LEGACY_CONFIG_FILE = os.path.join(get_app_dir(), 'autorunsql.ini')


def _write_config(config, config_path=None):
    if config_path is None:
        config_path = CONFIG_FILE
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    persisted = configparser.ConfigParser(interpolation=None)
    for section in config.sections():
        persisted[section] = dict(config[section])
    if 'Database' in persisted and 'password' in persisted['Database']:
        persisted['Database']['password'] = json.dumps(
            config['Database']['password'], ensure_ascii=False
        )
        persisted['Database']['password_encoding'] = 'json-v1'
    with open(config_path, 'w', encoding='utf-8') as config_file:
        persisted.write(config_file)


def build_connection_string(db_config):
    connection_string = db_config.get('connection_string', '')
    if '\r' in connection_string or '\n' in connection_string:
        raise ValueError("连接字符串不能包含换行")
    connection_string = connection_string.strip()
    if connection_string:
        return connection_string

    required_fields = ('user', 'host', 'port', 'service_name')
    if any(not db_config.get(field, '').strip() for field in required_fields):
        return ''

    password = db_config.get('password', '')
    if password and not re.fullmatch(r'[A-Za-z0-9_$#]+', password):
        password = '"' + password.replace('"', '""') + '"'
    return (
        f"{db_config['user']}/{password}@{db_config['host']}:"
        f"{db_config['port']}/{db_config['service_name']}"
    )


def has_oracle_error(text):
    return bool(re.search(r'\b(ORA|SP2|PLS|SQL|TNS|EXP|IMP)-\d+', text, re.IGNORECASE))


def strip_trailing_sql_comments(sql_content):
    effective = []
    index = 0
    quote = None
    while index < len(sql_content):
        char = sql_content[index]
        next_char = sql_content[index + 1:index + 2]

        if quote:
            effective.append(char)
            if char == quote:
                if next_char == quote:
                    effective.append(next_char)
                    index += 1
                else:
                    quote = None
            index += 1
            continue

        previous_char = sql_content[index - 1:index]
        previous_word_boundary = (
            not previous_char or not (
                previous_char.isalnum() or previous_char in '_$#'
            )
        )
        national_q_quote = (
            previous_char in ('n', 'N')
            and (index < 2 or not (
                sql_content[index - 2].isalnum()
                or sql_content[index - 2] in '_$#'
            ))
        )
        if (char in ('q', 'Q') and next_char == "'"
                and (previous_word_boundary or national_q_quote)):
            delimiter_index = index + 2
            if delimiter_index < len(sql_content):
                delimiter = sql_content[delimiter_index]
                closing_delimiter = {
                    '[': ']',
                    '{': '}',
                    '(': ')',
                    '<': '>'
                }.get(delimiter, delimiter)
                end_markers = (
                    ("'''", "''") if delimiter == "'"
                    else (closing_delimiter + "'",)
                )
                end_index = -1
                end_marker_length = 0
                for marker in end_markers:
                    marker_index = sql_content.find(
                        marker, delimiter_index + 1
                    )
                    if marker_index != -1 and (
                            end_index == -1 or marker_index < end_index):
                        end_index = marker_index
                        end_marker_length = len(marker)
                if end_index != -1:
                    end = end_index + end_marker_length
                    effective.append(sql_content[index:end])
                    index = end
                    continue

        if char in ("'", '"'):
            quote = char
            effective.append(char)
            index += 1
            continue

        if char == '-' and next_char == '-':
            newline_index = index + 2
            while (newline_index < len(sql_content)
                   and sql_content[newline_index] not in '\r\n'):
                newline_index += 1
            if newline_index == len(sql_content):
                break
            line_end = newline_index + 1
            if (sql_content[newline_index] == '\r'
                    and line_end < len(sql_content)
                    and sql_content[line_end] == '\n'):
                line_end += 1
            effective.append(sql_content[newline_index:line_end])
            index = line_end
            continue

        if char == '/' and next_char == '*':
            end_index = sql_content.find('*/', index + 2)
            if end_index == -1:
                break
            effective.append(' ')
            index = end_index + 2
            continue

        effective.append(char)
        index += 1

    return ''.join(effective).rstrip()


def load_config():
    config = configparser.ConfigParser(interpolation=None)
    modified = False
    migrating_legacy_config = (
        not os.path.exists(CONFIG_FILE) and os.path.exists(LEGACY_CONFIG_FILE)
    )
    if not os.path.exists(CONFIG_FILE):
        if migrating_legacy_config:
            config_path = LEGACY_CONFIG_FILE
            modified = True
        else:
            modified = True
    else:
        config_path = CONFIG_FILE

    if migrating_legacy_config or os.path.exists(CONFIG_FILE):
        try:
            with open(config_path, 'r', encoding='utf-8-sig') as config_file:
                config.read_file(config_file)
            if 'Database' in config:
                database = config['Database']
                password = database.get('password', '')
                if database.get('password_encoding') == 'json-v1':
                    password = json.loads(password)
                    if not isinstance(password, str):
                        raise ValueError("密码字段格式无效")
                    database['password'] = password
                    del database['password_encoding']
                elif password.startswith('json-v1:'):
                    try:
                        legacy_password = json.loads(password[8:])
                    except ValueError:
                        legacy_password = password
                    if isinstance(legacy_password, str):
                        database['password'] = legacy_password
        except (UnicodeDecodeError, configparser.Error, OSError, ValueError) as e:
            messagebox.showerror(
                "配置读取失败",
                "{}\n{}\n请修复或删除该配置文件后重试。".format(config_path, e)
            )
            config = configparser.ConfigParser(interpolation=None)
            for section, options in DEFAULT_CONFIG.items():
                config[section] = options
            try:
                _write_config(config)
            except OSError as write_error:
                messagebox.showwarning(
                    "配置恢复失败",
                    "已在内存中使用默认配置，但无法写入默认配置文件："
                    "\n{}\n{}".format(CONFIG_FILE, write_error)
                )
            return config

    for section, options in DEFAULT_CONFIG.items():
        if section not in config:
            config[section] = {}
            modified = True
        for key, value in options.items():
            if key not in config[section]:
                config[section][key] = value
                modified = True

    if modified:
        _write_config(config)
        if migrating_legacy_config:
            try:
                _write_config(config, LEGACY_CONFIG_FILE)
            except OSError as e:
                messagebox.showwarning(
                    "配置迁移提醒",
                    "新配置已保存，但旧配置文件无法覆盖，"
                    "其中可能仍有明文凭据：\n{}\n{}".format(
                        LEGACY_CONFIG_FILE, e
                    )
                )
        elif not os.path.exists(LEGACY_CONFIG_FILE):
            messagebox.showinfo("提示", f"配置文件已自动生成：{CONFIG_FILE}")

    return config

# ================== SQL*Plus 执行器 ==================
class SQLPlusExecutor:
    MAX_AUTO_REPLACE_CHARS = 3   # 自动替换字符的阈值

    def __init__(self, db_config, sqlplus_path, log_callback=None):
        self.db_config = db_config
        self.sqlplus_path = sqlplus_path
        self.log_callback = log_callback
        self._log_callback_lock = threading.Lock()
        try:
            self.connection_string = build_connection_string(db_config)
            self.connection_error = ''
        except ValueError as e:
            self.connection_string = ''
            self.connection_error = str(e)
        self.current_process = None
        self._process_lock = threading.Lock()
        self.stop_requested = False

        os.environ['NLS_LANG'] = 'AMERICAN_AMERICA.ZHS16GBK'
        self.log("已设置 NLS_LANG=AMERICAN_AMERICA.ZHS16GBK", "INFO")

    def log(self, message, level="INFO"):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        if sys.stdout is not None:
            print(log_line)
        self._send_log_callback(log_line + "\n")

    def _send_log_callback(self, text):
        callback_error = None
        with self._log_callback_lock:
            if self.log_callback:
                try:
                    self.log_callback(text)
                except Exception as e:
                    callback_error = e
                    self.log_callback = None
        if callback_error:
            self.log(
                "日志回调失败，已停用界面日志回调：{}".format(callback_error),
                "WARNING"
            )

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
        effective = strip_trailing_sql_comments(sql_content)
        lines = effective.splitlines()
        if not lines:
            return sql_content
        last_line = lines[-1].rstrip()
        if re.match(r'.*\bEND\s*;\s*$', last_line, re.IGNORECASE):
            if not re.search(r'(?:^|\n)\s*/\s*$', effective):
                return sql_content.rstrip() + '\n/\n'
        return sql_content

    def stop(self):
        self.stop_requested = True
        with self._process_lock:
            process = self.current_process
        if process and process.poll() is None:
            self.log("正在终止进程...", "WARNING")
            try:
                process.terminate()
                self.log("终止信号已发送。", "WARNING")
            except OSError as e:
                self.log(f"终止进程出错: {e}", "ERROR")

    def _has_oracle_error(self, text):
        return has_oracle_error(text)

    def execute_sql_file(self, file_path, show_command=False):
        if not os.path.isfile(self.sqlplus_path):
            self.log(f"sqlplus 路径无效: {self.sqlplus_path}", "ERROR")
            return False

        if self.stop_requested:
            self.log("用户停止，跳过此文件。", "WARNING")
            return False

        if not os.path.exists(file_path):
            self.log(f"文件不存在: {file_path}", "ERROR")
            return False

        self.log(f"开始执行: {file_path}")

        # 读取文件
        content = None
        for enc in ['utf-8-sig', 'gbk']:
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
        processed_content = content_with_slash
        executable_content = strip_trailing_sql_comments(processed_content)
        if not re.search(r'\b(?:EXIT|QUIT)\s*;?\s*$', executable_content, re.IGNORECASE):
            processed_content += "\nEXIT;\n"

        # 编码检查：少量字符自动替换，超阈值直接失败
        try:
            processed_content.encode('gbk')
        except UnicodeEncodeError as e:
            bad_count = self._count_unencodable_chars(processed_content, 'gbk')
            if bad_count <= self.MAX_AUTO_REPLACE_CHARS:
                self.log(f"{bad_count} 个字符无法转换为 GBK，自动使用替换字符执行", "WARNING")
            else:
                self.log(f"文件包含 {bad_count} 个无法转换的字符，已跳过: {e}", "ERROR")
                return False

        conn_str = self.connection_string
        if not conn_str:
            self.log(self.connection_error or "连接字符串为空", "ERROR")
            return False
        try:
            conn_str.encode('gbk')
        except UnicodeEncodeError as e:
            self.log(f"连接信息包含无法转换为 GBK 的字符，已跳过: {e}", "ERROR")
            return False

        if show_command:
            self.log(f'命令: "{self.sqlplus_path}" -S -L /nolog <连接信息已隐藏>')

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        sqlplus_input = "SET DEFINE OFF;\nCONNECT " + conn_str + "\n" + processed_content

        try:
            process = subprocess.Popen(
                [self.sqlplus_path, "-S", "-L", "/nolog"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding='gbk',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            )
            with self._process_lock:
                self.current_process = process
                stop_was_requested = self.stop_requested
            if stop_was_requested:
                process.terminate()

            stdout_chunks = []
            stderr_chunks = []
            thread_errors = []
            stream_close_errors = []

            def write_input():
                try:
                    process.stdin.write(sqlplus_input)
                except Exception as e:
                    thread_errors.append(("stdin", e))
                try:
                    process.stdin.close()
                except Exception as e:
                    thread_errors.append(("stdin", e))

            def read_output(stream, chunks, name):
                try:
                    while True:
                        chunk = stream.readline(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                except Exception as e:
                    thread_errors.append((name, e))
                finally:
                    try:
                        stream.close()
                    except Exception as e:
                        stream_close_errors.append((name, e))

            writer = threading.Thread(target=write_input, daemon=True)
            stdout_reader = threading.Thread(
                target=read_output,
                args=(process.stdout, stdout_chunks, "stdout"),
                daemon=True
            )
            stderr_reader = threading.Thread(
                target=read_output,
                args=(process.stderr, stderr_chunks, "stderr"),
                daemon=True
            )
            writer.start()
            stdout_reader.start()
            stderr_reader.start()

            termination_deadline = None
            kill_deadline = None
            kill_sent = False
            process_timed_out = False
            try:
                while process.poll() is None:
                    now = time.monotonic()
                    if self.stop_requested and termination_deadline is None:
                        termination_deadline = now + 2
                    if (termination_deadline is not None
                            and now >= termination_deadline
                            and not kill_sent):
                        try:
                            process.kill()
                            kill_sent = True
                            kill_deadline = now + 5
                            self.log("已发送强制终止信号。", "WARNING")
                        except OSError as e:
                            kill_sent = True
                            kill_deadline = now + 5
                            self.log(f"强制终止进程失败: {e}", "ERROR")
                    elif (kill_deadline is not None and now >= kill_deadline
                          and process.poll() is None):
                        self.log(
                            "SQL*Plus 进程在强制终止后仍未退出，"
                            "停止等待；请在任务管理器中检查该进程。",
                            "ERROR"
                        )
                        self.stop_requested = True
                        process_timed_out = True
                        break
                    time.sleep(0.1)
            finally:
                writer.join(timeout=2)
                stdout_reader.join(timeout=2)
                stderr_reader.join(timeout=2)
                with self._process_lock:
                    if self.current_process is process:
                        self.current_process = None

            retcode = process.returncode
            stdout = ''.join(stdout_chunks)
            stderr = ''.join(stderr_chunks)
            for stream_name, error in stream_close_errors:
                self.log(
                    f"关闭 SQL*Plus {stream_name} 流时出错: {error}",
                    "WARNING"
                )
            relevant_thread_errors = []
            for stream_name, error in thread_errors:
                if (stream_name == "stdin"
                        and isinstance(error, BrokenPipeError)
                        and process.poll() is not None):
                    continue
                relevant_thread_errors.append((stream_name, error))
                self.log(
                    f"读取 SQL*Plus {stream_name} 时出错: {error}",
                    "ERROR"
                )

            if process_timed_out or process.poll() is None:
                return False
            if relevant_thread_errors:
                return False

            combined = stdout + stderr
            error_lines = [
                line for line in combined.splitlines()
                if re.search(
                    r'\b(ORA|SP2|PLS|SQL|TNS|EXP|IMP)-\d+',
                    line,
                    re.IGNORECASE
                )
            ]

            has_error = bool(error_lines)
            if retcode == 0 and not has_error:
                self.log(f"成功: {file_path}")
                return True
            if self.stop_requested:
                self.log(f"已停止执行: {file_path}", "WARNING")
                for line in error_lines:
                    self.log(line, "WARNING")
                return False
            if has_error:
                self.log(f"SQL 执行错误: {file_path}", "WARNING")
                for line in error_lines:
                    self.log(line, "ERROR")
                return False

            self.log(f"失败 (返回码 {retcode}): {file_path}", "ERROR")
            tail_lines = [
                line for line in combined.splitlines()
                if line.strip()
                and not re.fullmatch(r'[\d\s.,+-]+', line)
            ][-10:]
            diagnostic_lines = error_lines or tail_lines
            for line in diagnostic_lines:
                self.log(line, "ERROR")
            if not diagnostic_lines:
                self.log("SQL*Plus 未提供错误输出。", "ERROR")
            return False
        except Exception as e:
            self.log(f"执行异常: {e}", "ERROR")
            return False

    def execute_folder(self, folder_path, extension=".sql", sort_files=True):
        if not os.path.isdir(folder_path):
            self.log(f"文件夹不存在: {folder_path}", "ERROR")
            return False, []

        sql_files = []
        for root, _, files in os.walk(folder_path):
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
        stopped = False

        for idx, file_path in enumerate(sql_files, 1):
            if self.stop_requested:
                self.log("用户停止，终止后续执行", "WARNING")
                stopped = True
                break

            show_cmd = (idx == 1)
            success = self.execute_sql_file(file_path, show_command=show_cmd)

            if success:
                success_files.append(file_path)
            elif not self.stop_requested:
                failed_files.append(file_path)
            if self.stop_requested:
                stopped = True
                break

        if stopped:
            self.log(
                f"批量已停止：成功 {len(success_files)} 个，"
                f"失败 {len(failed_files)} 个，未执行 {len(sql_files) - len(success_files) - len(failed_files)} 个",
                "WARNING"
            )
        else:
            self.log(f"批量完成：成功 {len(success_files)} 个，失败 {len(failed_files)} 个")
        if failed_files:
            self.log("失败列表：")
            for f in failed_files:
                self.log(f"  - {f}", "ERROR")
        return not stopped and len(failed_files) == 0, failed_files

# ================== 设置窗口 ==================
class SettingsWindow:
    # ---- 统一字体与间距 ----
    FONT_TITLE  = ("Microsoft YaHei", 11, "bold")
    FONT_LABEL  = ("Microsoft YaHei", 10)
    FONT_ENTRY  = ("Microsoft YaHei", 10)
    FONT_HINT   = ("Microsoft YaHei", 9)
    FONT_BUTTON = ("Microsoft YaHei", 10)
    ROW_PADY    = 4      # 每行垂直间距（行距）
    SEC_PADY    = (2, 8) # 小节标题下方间距

    def __init__(self, parent, config, on_save_callback=None):
        self.parent = parent
        self.config = config
        self.on_save = on_save_callback
        self.window = Toplevel(parent)
        self.window.title("设置")
        self.window.geometry("640x600")
        self.window.minsize(520, 520)      # 允许自由缩放，但最小尺寸保证排版
        self.window.resizable(True, True)  # 关键：允许调整大小
        self.window.transient(parent)

        self._wraplength_widgets = []      # 需要随窗口宽度变化而更新换行的 Label
        self._resize_job = None
        self._ui_queue = queue.Queue()
        self._test_input_widgets = []

        # ---- 主容器 ----
        main_frame = tk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        main_frame.columnconfigure(1, weight=1)  # 让第 1 列（输入区）随窗口横向拉伸

        row = 0

        # ===== 数据库配置 =====
        tk.Label(main_frame, text="数据库配置", font=self.FONT_TITLE,
                 anchor="w").grid(row=row, column=0, columnspan=2,
                                  sticky="ew", pady=(0, 6))
        row += 1

        self.db_entries = {}
        for key in ['user', 'password', 'host', 'port', 'service_name']:
            tk.Label(main_frame, text=key + ":", font=self.FONT_LABEL,
                     anchor="e").grid(row=row, column=0, padx=(0, 8),
                                      pady=self.ROW_PADY, sticky="e")
            entry_options = {'width': 30, 'font': self.FONT_ENTRY}
            entry = tk.Entry(main_frame, **entry_options)
            entry.insert(0, self.config['Database'].get(key, ''))
            entry.grid(row=row, column=1, pady=self.ROW_PADY, sticky="ew")
            self.db_entries[key] = entry
            self._test_input_widgets.append(entry)
            row += 1

        # 连接字符串
        tk.Label(main_frame, text="连接字符串 (可选):", font=self.FONT_LABEL,
                 anchor="e").grid(row=row, column=0, padx=(0, 8),
                                  pady=self.ROW_PADY, sticky="e")
        self.conn_str_var = tk.StringVar(value=self.config['Database'].get('connection_string', ''))
        self.conn_str_entry = tk.Entry(
            main_frame, textvariable=self.conn_str_var, width=30,
            font=self.FONT_ENTRY
        )
        self.conn_str_entry.grid(
            row=row, column=1, pady=self.ROW_PADY, sticky="ew")
        self._test_input_widgets.append(self.conn_str_entry)
        row += 1

        # 连接串提示（自适应换行）
        conn_hint = (
            "可填写两种字符串格式，若填写该参数则忽略上方所有参数：\n"
            "1) zcgl/zcgl@数据库连接别名 —— 该写法可用于连接无跳板机、"
            "仅有堡垒机的 Linux 数据库；\n"
            "2) zcgl/zcgl@主机IP:端口/服务名 —— 简易连接串写法。"
        )
        self.conn_hint_label = tk.Label(
            main_frame, text=conn_hint, fg="gray", font=self.FONT_HINT,
            justify="left", anchor="w")
        self.conn_hint_label.grid(row=row, column=0, columnspan=2,
                                  pady=(2, 10), sticky="ew")
        self._wraplength_widgets.append(self.conn_hint_label)
        row += 1

        # 测试连接
        self.test_btn = tk.Button(main_frame, text="测试连接", command=self.test_connection,
                                  bg="lightblue", font=self.FONT_BUTTON, width=12)
        self.test_btn.grid(row=row, column=0, columnspan=2, pady=(2, 14))
        row += 1

        # ===== SQL*Plus 设置 =====
        tk.Label(main_frame, text="SQL*Plus 设置", font=self.FONT_TITLE,
                 anchor="w").grid(row=row, column=0, columnspan=2,
                                  sticky="ew", pady=(0, 6))
        row += 1

        # sqlplus 路径行（单独一个 frame，让 Entry 也能横向拉伸）
        path_frame = tk.Frame(main_frame)
        path_frame.grid(row=row, column=0, columnspan=2, sticky="ew",
                        pady=self.ROW_PADY)
        path_frame.columnconfigure(1, weight=1)

        tk.Label(path_frame, text="sqlplus 路径:", font=self.FONT_LABEL,
                 anchor="e").grid(row=0, column=0, padx=(0, 8), sticky="e")
        self.sqlplus_path_var = tk.StringVar(value=self.config['Sqlplus'].get('path', ''))
        self.sqlplus_path_entry = tk.Entry(
            path_frame, textvariable=self.sqlplus_path_var,
            font=self.FONT_ENTRY
        )
        self.sqlplus_path_entry.grid(row=0, column=1, sticky="ew")
        self._test_input_widgets.append(self.sqlplus_path_entry)
        self.find_sqlplus_button = tk.Button(
            path_frame, text="获取路径", command=self.find_sqlplus_path,
            font=self.FONT_BUTTON
        )
        self.find_sqlplus_button.grid(row=0, column=2, padx=(6, 0))
        self._test_input_widgets.append(self.find_sqlplus_button)
        self.browse_sqlplus_button = tk.Button(
            path_frame, text="浏览", command=self.browse_sqlplus,
            font=self.FONT_BUTTON
        )
        self.browse_sqlplus_button.grid(row=0, column=3, padx=(6, 0))
        self._test_input_widgets.append(self.browse_sqlplus_button)
        row += 1

        self.sqlplus_hint_label = tk.Label(
            main_frame, text="确保 sqlplus.exe 路径正确且可运行。", fg="gray",
            font=self.FONT_HINT, justify="left", anchor="w")
        self.sqlplus_hint_label.grid(row=row, column=0, columnspan=2,
                                     pady=(2, 10), sticky="ew")
        self._wraplength_widgets.append(self.sqlplus_hint_label)
        row += 1

        # 保存 / 取消
        btn_frame = tk.Frame(main_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=15)
        self.save_button = tk.Button(
            btn_frame, text="保存", command=self.save_settings,
            width=10, font=self.FONT_BUTTON
        )
        self.save_button.pack(side=tk.LEFT, padx=10)
        self._test_input_widgets.append(self.save_button)
        tk.Button(btn_frame, text="取消", command=self.window.destroy,
                  width=10, font=self.FONT_BUTTON).pack(side=tk.LEFT, padx=10)

        # ---- 自适应：监听窗口尺寸变化 ----
        self.window.bind("<Configure>", self._on_configure)
        self.window.after(50, self._update_wraplength)
        self.window.after(50, self._process_ui_queue)

    def _post_to_ui(self, callback, *args, **kwargs):
        self._ui_queue.put((callback, args, kwargs))

    def _process_ui_queue(self):
        if not self.window.winfo_exists():
            return
        while True:
            try:
                callback, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args, **kwargs)
            except Exception:
                if not self.window.winfo_exists():
                    return
                self.window.report_callback_exception(*sys.exc_info())
            if not self.window.winfo_exists():
                return
        self.window.after(50, self._process_ui_queue)

    # ---- 窗口尺寸变化 → 防抖更新 wraplength ----
    def _on_configure(self, event):
        if event.widget is not self.window:
            return
        if self._resize_job is not None:
            self.window.after_cancel(self._resize_job)
        self._resize_job = self.window.after(30, self._update_wraplength)

    def _update_wraplength(self):
        w = self.window.winfo_width()
        if w <= 1:  # 窗口尚未映射完成
            return
        wrap = max(w - 60, 200)  # 预留左右内边距 + 安全边距
        for lbl in self._wraplength_widgets:
            try:
                lbl.config(wraplength=wrap)
            except tk.TclError:
                pass

    # ---- 其余方法与原实现保持一致 ----
    def browse_sqlplus(self):
        path = filedialog.askopenfilename(title="选择 sqlplus.exe",
                                          filetypes=[("Executable", "*.exe"),
                                                     ("All files", "*.*")])
        if path:
            self.sqlplus_path_var.set(path)

    def find_sqlplus_path(self):
        configured_path = self.sqlplus_path_var.get().strip()
        candidates = [configured_path]
        oracle_home = os.environ.get("ORACLE_HOME")
        if oracle_home:
            candidates.append(os.path.join(oracle_home, "bin", "sqlplus.exe"))
        candidates.extend([
            shutil.which("sqlplus.exe") or "",
            shutil.which("sqlplus") or "",
        ])
        for path in candidates:
            if path and os.path.isfile(path):
                self.sqlplus_path_var.set(os.path.abspath(path))
                return
        messagebox.showwarning("未找到 SQL*Plus",
                               "未能自动找到 sqlplus.exe，请手动填写 SQL*Plus 路径。",
                               parent=self.window)

    def _save_settings(self):
        connection_string = self.conn_str_var.get()
        try:
            validated_connection_string = build_connection_string({
                'connection_string': connection_string,
                'user': self.db_entries['user'].get().strip(),
                'password': self.db_entries['password'].get(),
                'host': self.db_entries['host'].get().strip(),
                'port': self.db_entries['port'].get().strip(),
                'service_name': self.db_entries['service_name'].get().strip()
            })
        except ValueError as e:
            raise ValueError("连接字符串无效：{}".format(e))
        if not validated_connection_string:
            raise ValueError(
                "请填写连接字符串，或完整填写 user、host、port 和 service_name。"
            )

        for key, entry in self.db_entries.items():
            value = entry.get()
            self.config['Database'][key] = (
                value if key == 'password' else value.strip()
            )
        self.config['Database']['connection_string'] = connection_string.strip()
        self.config['Sqlplus']['path'] = self.sqlplus_path_var.get().strip()
        _write_config(self.config)
        if self.on_save:
            self.on_save(self.config)

    def save_settings(self):
        try:
            self._save_settings()
        except ValueError as e:
            messagebox.showerror("保存失败", str(e), parent=self.window)
            return
        except OSError as e:
            messagebox.showerror("保存失败", f"无法保存配置：{e}", parent=self.window)
            return
        messagebox.showinfo("成功", "配置已保存并立即生效。")

    def test_connection(self):
        sqlplus_path = self.sqlplus_path_var.get().strip()
        if not sqlplus_path or not os.path.isfile(sqlplus_path):
            messagebox.showwarning(
                "提示",
                "SQL*Plus 路径无效：{}".format(sqlplus_path or "未填写"),
                parent=self.window
            )
            return

        user = self.db_entries['user'].get().strip()
        password = self.db_entries['password'].get()
        host = self.db_entries['host'].get().strip()
        port = self.db_entries['port'].get().strip()
        service_name = self.db_entries['service_name'].get().strip()
        conn_str_input = self.conn_str_var.get()

        try:
            conn_str = build_connection_string({
                'connection_string': conn_str_input,
                'user': user,
                'password': password,
                'host': host,
                'port': port,
                'service_name': service_name
            })
        except ValueError as e:
            messagebox.showerror("连接失败", str(e), parent=self.window)
            return

        if not conn_str or not sqlplus_path:
            messagebox.showwarning("警告", "请填写完整的连接信息和 SQL*Plus 路径")
            return
        try:
            conn_str.encode('gbk')
        except UnicodeEncodeError:
            messagebox.showerror("连接失败", "连接信息包含无法转换为 GBK 的字符。")
            return

        self.test_btn.config(state=tk.DISABLED, text="测试中...")
        for widget in self._test_input_widgets:
            widget.config(state=tk.DISABLED)

        def do_test():
            try:
                test_sql = "SELECT 1 FROM DUAL;\nEXIT;\n"
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                proc = subprocess.Popen(
                    [sqlplus_path, "-S", "-L", "/nolog"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    encoding='gbk',
                    errors='replace',
                    startupinfo=startupinfo,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                )
                try:
                    stdout, stderr = proc.communicate(
                        input="SET DEFINE OFF;\nCONNECT " + conn_str + "\n" + test_sql,
                        timeout=10
                    )
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate()
                    self._post_to_ui(
                        messagebox.showerror,
                        "连接失败", "连接超时（10秒）", parent=self.window
                    )
                    return
                combined = stdout + stderr
                if proc.returncode == 0 and not has_oracle_error(combined):
                    self._post_to_ui(self._on_test_success)
                else:
                    err_msg = combined.strip() or "未知错误"
                    self._post_to_ui(
                        messagebox.showerror, "连接失败",
                        f"连接失败，错误信息：\n{err_msg}",
                        parent=self.window
                    )
            except Exception as e:
                error_message = str(e)
                self._post_to_ui(
                    messagebox.showerror, "连接失败",
                    f"测试过程出错：{error_message}", parent=self.window
                )
            finally:
                self._post_to_ui(self._reset_test_button)

        threading.Thread(target=do_test, daemon=True).start()

    def _on_test_success(self):
        try:
            self._save_settings()
        except ValueError as e:
            messagebox.showerror("保存失败", str(e), parent=self.window)
            return
        except OSError as e:
            messagebox.showerror(
                "保存失败", "无法保存配置：{}".format(e), parent=self.window
            )
            return

        messagebox.showinfo(
            "连接成功",
            "数据库连接测试成功，配置已自动保存并生效，即将关闭设置窗口。",
            parent=self.window
        )
        self.window.destroy()

    def _reset_test_button(self):
        if self.window.winfo_exists():
            self.test_btn.config(state=tk.NORMAL, text="测试连接")
            for widget in self._test_input_widgets:
                widget.config(state=tk.NORMAL)

# ================== 主 GUI ==================
class Application:
    def __init__(self, root):
        self.root = root
        self.root.title("Oracle SQL 批量执行工具 v0.3.1 ")
        self.root.geometry("850x750")
        self.ui_queue = queue.Queue()
        self._finish_received = False

        self.config = load_config()
        self.db_config = dict(self.config['Database'])
        self.sqlplus_path = self.config['Sqlplus']['path']

        self.executor = None
        self.running_executor = None
        self.running = False
        self._closing = False
        self.settings_window = None

        # GUI 控件
        frame_top = tk.Frame(root)
        frame_top.pack(pady=10, fill=tk.X)

        tk.Label(frame_top, text="选择要执行的SQL文件或文件夹：").pack(side=tk.LEFT, padx=5)
        self.path_var = tk.StringVar()
        tk.Entry(frame_top, textvariable=self.path_var, width=50).pack(side=tk.LEFT, padx=5)
        tk.Button(frame_top, text="浏览文件", command=self.select_file).pack(side=tk.LEFT, padx=2)
        tk.Button(frame_top, text="浏览文件夹", command=self.select_folder).pack(side=tk.LEFT, padx=2)
        tk.Button(frame_top, text="设置", command=self.open_settings, bg="lightblue").pack(side=tk.LEFT, padx=10)
        tk.Button(frame_top, text="使用说明", command=self.show_update_log, bg="lightyellow").pack(side=tk.LEFT, padx=5)

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
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(50, self._process_ui_queue)

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
        win.title("使用说明")
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
        if self.settings_window and self.settings_window.window.winfo_exists():
            self.settings_window.window.lift()
            self.settings_window.window.focus_force()
            return
        self.settings_window = SettingsWindow(self.root, self.config, on_save_callback=self.on_settings_saved)
        self.settings_window.window.lift()
        self.settings_window.window.focus_force()

    def toggle_copy_dir(self):
        state = tk.NORMAL if self.copy_failed_enabled.get() else tk.DISABLED
        self.copy_dir_entry.config(state=state)
        self.browse_copy_btn.config(state=state)

    def browse_copy_dir(self):
        path = filedialog.askdirectory(title="选择存放失败文件的文件夹")
        if path:
            self.copy_dir_var.set(path)

    def append_log(self, text):
        self.ui_queue.put(('log', text))

    def clear_log(self):
        self.log_area.delete(1.0, tk.END)

    def update_status(self, text):
        self.ui_queue.put(('status', text))

    def _process_ui_queue(self):
        if not self.root.winfo_exists():
            return
        log_batch = []
        log_batch_chars = 0
        processed_items = 0
        batch_started = time.monotonic()

        def flush_log_batch():
            nonlocal log_batch_chars
            if log_batch:
                self.log_area.insert(tk.END, ''.join(log_batch))
                self.log_area.see(tk.END)
                log_batch[:] = []
                log_batch_chars = 0

        while (processed_items < 200
               and time.monotonic() - batch_started < 0.01
               and log_batch_chars < 256 * 1024):
            try:
                action, value = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            processed_items += 1
            if action == 'log':
                if not self._closing:
                    log_batch.append(value)
                    log_batch_chars += len(value)
            elif action == 'status':
                flush_log_batch()
                self.status_var.set(value)
            elif action == 'finish':
                flush_log_batch()
                success, stopped = value
                self._finish_execution(success, stopped)
                if self._closing:
                    self._finish_received = True
            if not self.root.winfo_exists():
                return
        flush_log_batch()
        if self._closing and self._finish_received:
            self.root.update_idletasks()
            self.root.destroy()
            return
        delay = 10 if not self.ui_queue.empty() else 50
        self.root.after(delay, self._process_ui_queue)

    def on_close(self):
        if self._closing:
            return
        if self.running:
            if not messagebox.askyesno(
                    "任务正在运行",
                    "关闭程序需要停止当前任务。确定停止并关闭吗？",
                    parent=self.root):
                return
            self._closing = True
            self.status_var.set("正在停止任务并关闭...")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            if (self.settings_window
                    and self.settings_window.window.winfo_exists()):
                self.settings_window.window.destroy()
            executor = self.running_executor or self.executor
            if executor:
                executor.stop()
            return
        if (self.settings_window
                and self.settings_window.window.winfo_exists()):
            self.settings_window.window.destroy()
        self.root.destroy()

    def stop_execution(self):
        executor = self.running_executor or self.executor
        if self.running and executor:
            self.append_log("\n用户请求停止任务...\n")
            executor.stop()
            self.stop_button.config(state=tk.DISABLED)
            self.update_status("正在停止...")

    def copy_failed_files(self, failed_files, source_root, target_root=None):
        if not failed_files:
            return
        if target_root is None:
            target_root = self.copy_dir_var.get().strip()
        if not target_root:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            target_root = os.path.join(get_app_dir(), f"failed_{timestamp}")
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

        executor = self.executor
        if executor is None:
            messagebox.showerror("错误", "SQL*Plus 执行器尚未初始化。")
            return
        self.running_executor = executor
        copy_failed_enabled = self.copy_failed_enabled.get()
        copy_target = self.copy_dir_var.get().strip()
        self.running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.update_status("正在执行...")

        def run():
            failed_files = []
            success = False
            try:
                if os.path.isfile(target):
                    success = executor.execute_sql_file(target, show_command=True)
                    if not success and not executor.stop_requested:
                        failed_files = [target]
                    if success:
                        self.append_log("\n执行成功。\n")
                    elif executor.stop_requested:
                        self.append_log("\n任务已停止。\n")
                    else:
                        self.append_log("\n执行失败。\n")
                else:
                    success, failed_files = executor.execute_folder(target, sort_files=True)
                    if success:
                        self.append_log("\n全部执行完毕。\n")
                    elif executor.stop_requested:
                        self.append_log(
                            f"\n任务已停止，已执行失败 {len(failed_files)} 个文件。\n"
                        )
                    else:
                        self.append_log(f"\n共 {len(failed_files)} 个文件失败。\n")
            except Exception as e:
                self.append_log(f"\n异常: {e}\n")
                self.update_status("执行出错")
            finally:
                if copy_failed_enabled and failed_files:
                    try:
                        self.append_log("\n复制失败文件...\n")
                        self.copy_failed_files(failed_files, target, copy_target)
                    except Exception as e:
                        self.append_log(f"\n复制失败文件时出错: {e}\n")
                stopped = executor.stop_requested and not success
                executor.stop_requested = False
                self.running = False
                if self.running_executor is executor:
                    self.running_executor = None
                self.ui_queue.put(('finish', (success, stopped)))

        threading.Thread(target=run, daemon=True).start()

    def _finish_execution(self, success, stopped):
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        if stopped:
            self.status_var.set("已停止")
        else:
            self.status_var.set("完成" if success else "失败")

if __name__ == "__main__":
    root = tk.Tk()
    app = Application(root)
    root.mainloop()