#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oracle SQL 批量执行工具 - Linux 命令行版
兼容: Python 3.6+ / 主流 Linux 发行版
"""

import os
import re
import sys
import argparse
import datetime
import signal
import subprocess
import time
import shutil
import configparser

# ================== 默认配置 ==================
DEFAULT_CONFIG = {
    'Database': {
        'user': 'zcgl',
        'password': 'zcgl',
        'host': '10.3.3.121',
        'port': '1521',
        'service_name': 'shitan',
    },
    'Sqlplus': {
        'path': '/usr/bin/sqlplus'
    }
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'autorunsql.ini')


def load_config(config_file):
    """读取配置文件，不存在则生成默认配置并补全缺失项"""
    config = configparser.ConfigParser()
    needs_write = False

    if not os.path.exists(config_file):
        for section, options in DEFAULT_CONFIG.items():
            config[section] = dict(options)
        needs_write = True
    else:
        config.read(config_file, encoding='utf-8')
        for section, options in DEFAULT_CONFIG.items():
            if not config.has_section(section):
                config.add_section(section)
                needs_write = True
            for key, value in options.items():
                if not config.has_option(section, key):
                    config.set(section, key, value)
                    needs_write = True

    if needs_write:
        with open(config_file, 'w', encoding='utf-8') as f:
            config.write(f)
        print(f"[INFO] 已生成/补全配置文件: {config_file}", flush=True)

    return config


# ================== SQL*Plus 执行器 ==================
class SQLPlusExecutor:
    MAX_AUTO_REPLACE_CHARS = 3  # 自动替换字符的阈值

    def __init__(self, db_config, sqlplus_path):
        self.db_config = db_config
        self.sqlplus_path = sqlplus_path
        self.current_process = None
        self.stop_requested = False

        # 与 Windows 版保持一致
        os.environ['NLS_LANG'] = 'AMERICAN_AMERICA.ZHS16GBK'
        self.log("已设置 NLS_LANG=AMERICAN_AMERICA.ZHS16GBK", "INFO")

    def log(self, message, level="INFO"):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}", flush=True)

    @staticmethod
    def _count_unencodable_chars(text, encoding='gbk'):
        count = 0
        for ch in text:
            try:
                ch.encode(encoding)
            except UnicodeEncodeError:
                count += 1
        return count

    def ensure_plsql_slash(self, sql_content):
        """
        若整个 SQL 内容末尾有效部分是 END; 且后面没有单独的 '/'，则自动补 '/'
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
        """停止当前执行（信号处理器中调用，不打印，避免重入）"""
        self.stop_requested = True
        p = self.current_process
        if p and p.poll() is None:
            try:
                # 通过进程组终止，覆盖 sqlplus 可能产生的子进程
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                try:
                    p.terminate()
                except Exception:
                    pass

    @staticmethod
    def _kill_process(process):
        """超时后强制杀死整个进程组"""
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

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

        conn_str = (
            f"{self.db_config['user']}/{self.db_config['password']}"
            f"@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['service_name']}"
        )
        if not conn_str:
            self.log("连接字符串为空", "ERROR")
            return False

        # Linux 下用列表传参，无需 shell 转义
        cmd = [self.sqlplus_path, '-S', '-L', conn_str]
        if show_command:
            self.log(f"命令: {' '.join(cmd)}")

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding='gbk',
                errors=encoding_errors,
                start_new_session=True,   # 独立进程组，便于整组终止
            )
            self.current_process = process
            try:
                stdout, stderr = process.communicate(input=processed_content, timeout=30)
            except subprocess.TimeoutExpired:
                self._kill_process(process)
                stdout, stderr = process.communicate()
                self.log("执行超时（30秒）", "ERROR")
                return False
            finally:
                self.current_process = None

            retcode = process.returncode
            combined = (stdout or '') + (stderr or '')

            # 用户主动停止
            if self.stop_requested:
                self.log(f"用户停止，文件执行被中断: {file_path}", "WARNING")
                return False

            if self._has_oracle_error(combined):
                self.log(f"SQL 执行错误: {file_path}", "WARNING")
                if stdout and stdout.strip():
                    self.log(f"输出: {stdout.strip()}", "ERROR")
                if stderr and stderr.strip():
                    self.log(f"错误: {stderr.strip()}", "ERROR")
                return False

            if retcode == 0:
                self.log(f"成功: {file_path}")
                return True
            else:
                self.log(f"失败 (返回码 {retcode}): {file_path}", "ERROR")
                if stdout and stdout.strip():
                    self.log(f"输出: {stdout.strip()}", "ERROR")
                if stderr and stderr.strip():
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


# ================== 失败文件转存 ==================
def copy_failed_files(failed_files, source_root, target_root, executor):
    if not failed_files:
        return

    try:
        os.makedirs(target_root, exist_ok=True)
    except Exception as e:
        executor.log(f"创建失败文件目录出错: {e}", "ERROR")
        return

    copied = 0
    for f in failed_files:
        if os.path.isfile(source_root):
            rel = os.path.basename(f)
        else:
            rel = os.path.relpath(f, source_root)
        dest = os.path.join(target_root, rel)
        try:
            dest_dir = os.path.dirname(dest)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(f, dest)
            copied += 1
            executor.log(f"已复制: {rel} -> {dest}")
        except Exception as e:
            executor.log(f"复制失败 {f}: {e}", "ERROR")

    executor.log(f"共复制 {copied} 个失败文件到 {target_root}")


# ================== 主入口 ==================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Oracle SQL 批量执行工具 (Linux 命令行版)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用说明:\n"
            "  1. target 可以是单个 .sql 文件，也可以是递归扫描的目录。\n"
            "  2. 执行目录时默认按文件完整路径排序；--no-sort 可关闭排序。\n"
            "  3. --failed-dir 为必填项；失败文件会复制到此目录，目录不存在时自动创建。\n"
            "  4. --config 指定配置文件；首次运行会自动生成默认配置，"
            "默认位置为脚本目录下的 autorunsql.ini。\n"
            "  5. 配置项包括 [Database] 的 user/password/host/port/service_name，"
            "以及 [Sqlplus] 的 path。\n"
            "  6. 执行过程中按 Ctrl+C 可请求停止当前任务；已执行的 SQL 不会回滚。\n"
            "\n"
            "示例:\n"
            "  python3 autorunsql-linux.py ./deploy.sql --failed-dir ./failed\n"
            "  python3 autorunsql-linux.py ./sql_scripts --failed-dir ./failed\n"
            "  python3 autorunsql-linux.py ./sql_scripts --failed-dir ./failed "
            "--config /etc/autorunsql.ini --extension .sql\n"
            "  python3 autorunsql-linux.py ./sql_scripts --failed-dir ./failed --no-sort"
        )
    )
    parser.add_argument('target', help="要执行的 SQL 文件或包含 SQL 文件的目录")
    parser.add_argument(
        '--failed-dir', required=True,
        help="失败文件转存目录（必填，不存在会自动创建）"
    )
    parser.add_argument(
        '--config', default=CONFIG_FILE,
        help=f"配置文件路径，默认 {CONFIG_FILE}"
    )
    parser.add_argument(
        '--no-sort', action='store_true',
        help="不按路径排序（默认按全路径排序执行）"
    )
    parser.add_argument(
        '--extension', default='.sql',
        help="SQL 文件扩展名，默认 .sql"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.target):
        print(f"[ERROR] 路径不存在: {args.target}", file=sys.stderr, flush=True)
        return 2

    if not args.failed_dir or not args.failed_dir.strip():
        print("[ERROR] 必须指定失败文件转存目录", file=sys.stderr, flush=True)
        return 2

    config = load_config(args.config)
    db_config = dict(config['Database'])
    sqlplus_path = config['Sqlplus']['path'].strip()

    if not os.path.isfile(sqlplus_path):
        print(f"[ERROR] sqlplus 路径不存在: {sqlplus_path}", file=sys.stderr, flush=True)
        return 2
    if not os.access(sqlplus_path, os.X_OK):
        print(f"[ERROR] sqlplus 不可执行: {sqlplus_path}", file=sys.stderr, flush=True)
        return 2

    executor = SQLPlusExecutor(db_config, sqlplus_path)

    # Ctrl+C / SIGTERM 优雅停止
    def sig_handler(signum, frame):
        executor.stop()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    failed_files = []
    success = False

    try:
        if os.path.isfile(args.target):
            success = executor.execute_sql_file(args.target, show_command=True)
            if not success:
                failed_files = [args.target]
            print("\n执行成功。\n" if success else "\n执行失败。\n", flush=True)
        else:
            success, failed_files = executor.execute_folder(
                args.target,
                extension=args.extension,
                sort_files=not args.no_sort
            )
            if success:
                print("\n全部执行完毕。\n", flush=True)
            else:
                print(f"\n共 {len(failed_files)} 个文件失败。\n", flush=True)
    except KeyboardInterrupt:
        # 信号已由 handler 处理，这里兜底
        print("\n用户中断。\n", flush=True)
    finally:
        if failed_files:
            print("\n复制失败文件...\n", flush=True)
            copy_failed_files(failed_files, args.target, args.failed_dir, executor)

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())