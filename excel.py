import os
import platform
import re
import subprocess
from typing import List
from datetime import datetime

import pandas as pd
import pyperclip
import tkinter as tk
import xlwt
from openpyxl import Workbook
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from fuzzywuzzy import fuzz  # 用于模糊匹配

# ---------- 原有函数（周次展开、节次展开、Excel拆分/合并/信息）----------
def expand_weeks(text: str) -> str:
    if not text or not text.strip():
        return ""
    segments = [seg.strip() for seg in text.split(',') if seg.strip()]
    all_weeks = set()
    for seg in segments:
        parity = None
        match = re.search(r'[（(][单双][）)]', seg)
        if match:
            if match.group(0)[1] == '单':
                parity = 'odd'
            elif match.group(0)[1] == '双':
                parity = 'even'
            seg = re.sub(r'[（(][单双][）)]', '', seg)
        numbers = list(map(int, re.findall(r'\d+', seg)))
        if not numbers:
            continue
        if '-' in seg and len(numbers) >= 2:
            start, end = numbers[0], numbers[1]
            weeks = set(range(start, end + 1))
        else:
            weeks = {numbers[0]}
        if parity == 'odd':
            weeks = {w for w in weeks if w % 2 == 1}
        elif parity == 'even':
            weeks = {w for w in weeks if w % 2 == 0}
        all_weeks.update(weeks)
    if not all_weeks:
        return ""
    sorted_weeks = sorted(all_weeks)
    return ','.join(f"{w}周" for w in sorted_weeks)

def copy_to_clipboard(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run("clip", input=text.encode("gbk"), check=True)
        elif system == "Darwin":
            subprocess.run("pbcopy", input=text.encode("utf-8"), check=True)
        elif system == "Linux":
            subprocess.run("xclip -selection clipboard", input=text.encode("utf-8"), shell=True, check=True)
        else:
            return False
        return True
    except Exception:
        return False

def expand_sessions(week_num: int, session_str: str) -> List[str]:
    parts = [p.strip() for p in session_str.split(',') if p.strip()]
    result = []
    for part in parts:
        clean_part = part.replace('节', '')
        if '-' in clean_part:
            nums = list(map(int, re.findall(r'\d+', clean_part)))
            if len(nums) >= 2:
                start, end = nums[0], nums[1]
                for sess in range(start, end + 1):
                    result.append(f"{week_num}-{sess}")
        else:
            nums = re.findall(r'\d+', clean_part)
            if nums:
                result.append(f"{week_num}-{int(nums[0])}")
    seen = set()
    unique_result = []
    for item in result:
        if item not in seen:
            seen.add(item)
            unique_result.append(item)
    return unique_result

def split_excel_by_rows(file_path: str, rows_per_file: int = 65535, output_format: str = 'xlsx'):
    output_format = output_format.lower()
    if output_format not in {'xls', 'xlsx'}:
        raise ValueError("output_format 只能是 'xls' 或 'xlsx'")
    df = pd.read_excel(file_path)
    total_rows = len(df)
    header = df.columns.tolist()
    base_name = os.path.splitext(file_path)[0]
    output_files = []
    details = []
    for start_row in range(0, total_rows, rows_per_file):
        end_row = min(start_row + rows_per_file, total_rows)
        chunk = df.iloc[start_row:end_row]
        part_num = (start_row // rows_per_file) + 1
        output_file = f"{base_name}_第{part_num}部分.{output_format}"
        output_files.append(output_file)
        details.append((part_num, start_row + 1, end_row, len(chunk), output_file))
        if output_format == 'xls':
            workbook = xlwt.Workbook(encoding='utf-8')
            worksheet = workbook.add_sheet('Sheet1')
            for col_idx, col_name in enumerate(header):
                worksheet.write(0, col_idx, col_name)
            for row_idx, (_, row) in enumerate(chunk.iterrows(), start=1):
                for col_idx, value in enumerate(row):
                    worksheet.write(row_idx, col_idx, '' if pd.isna(value) else str(value))
            workbook.save(output_file)
        else:
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = 'Sheet1'
            for col_idx, col_name in enumerate(header, start=1):
                worksheet.cell(row=1, column=col_idx, value=col_name)
            for row_idx, (_, row) in enumerate(chunk.iterrows(), start=2):
                for col_idx, value in enumerate(row, start=1):
                    worksheet.cell(row=row_idx, column=col_idx, value='' if pd.isna(value) else value)
            workbook.save(output_file)
    return output_files, {"source_file": file_path, "total_rows": total_rows, "rows_per_file": rows_per_file, "output_count": len(output_files), "details": details}

def normalize_columns(columns) -> List[str]:
    return [str(col).strip() for col in columns]

def validate_header_consistency(frames: List[pd.DataFrame]) -> List[str]:
    if not frames:
        raise ValueError("没有可合并的数据。")
    expected = normalize_columns(frames[0].columns.tolist())
    for index, frame in enumerate(frames[1:], start=2):
        current = normalize_columns(frame.columns.tolist())
        if current != expected:
            raise ValueError(f"第 {index} 个工作表/文件的列标题与第 1 个不一致。\n期望：{expected}\n实际：{current}")
    return expected

def merge_excel_files(file_paths: List[str], output_path: str) -> str:
    if len(file_paths) < 2:
        raise ValueError("请至少选择 2 个 Excel 文件。")
    frames = [pd.read_excel(path) for path in file_paths]
    validate_header_consistency(frames)
    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged.to_excel(output_path, index=False)
    return output_path

def merge_excel_sheets(file_path: str, output_path: str) -> str:
    excel_file = pd.ExcelFile(file_path)
    sheet_names = excel_file.sheet_names
    if len(sheet_names) < 2:
        raise ValueError("请选择至少包含 2 个工作表的 Excel 文件。")
    frames = [pd.read_excel(file_path, sheet_name=name) for name in sheet_names]
    validate_header_consistency(frames)
    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged.to_excel(output_path, index=False)
    return output_path

def get_excel_summary(file_path: str) -> str:
    excel_file = pd.ExcelFile(file_path)
    lines = [f"文件：{file_path}", f"工作表数量：{len(excel_file.sheet_names)}"]
    for sheet_name in excel_file.sheet_names:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        lines.append(f"- 工作表 {sheet_name}: {len(df)} 行，{len(df.columns)} 列")
        lines.append(f"  列名：{list(df.columns)}")
    return "\n".join(lines)

# ---------- 数据清洗核心函数 ----------
def clean_data_with_ref(clean_df: pd.DataFrame, ref_df: pd.DataFrame,
                        clean_id_col: str, clean_name_col: str, clean_parent_col: str,
                        ref_id_col: str, ref_name_col: str, ref_parent_col: str,
                        threshold: int = 80) -> pd.DataFrame:
    result_df = clean_df.copy()
    result_df["匹配类型"] = ""
    result_df["匹配到的编号"] = ""
    result_df["匹配到的名称"] = ""
    result_df["匹配到的上级编号"] = ""

    ref_by_id = {}
    ref_by_name = {}
    for _, row in ref_df.iterrows():
        rid = str(row.get(ref_id_col, "")).strip()
        if rid:
            ref_by_id[rid] = row.to_dict()
        rname = str(row.get(ref_name_col, "")).strip()
        if rname:
            ref_by_name.setdefault(rname, []).append(row.to_dict())

    def clean_str(s):
        if not isinstance(s, str):
            return ""
        return re.sub(r'[（(].*?[）)]', '', s).strip()

    for idx, row in result_df.iterrows():
        clean_id = str(row.get(clean_id_col, "")).strip()
        clean_name = str(row.get(clean_name_col, "")).strip()
        clean_parent = str(row.get(clean_parent_col, "")).strip()
        matched = False
        match_type = ""
        match_id = ""
        match_name = ""
        match_parent = ""

        if clean_id in ref_by_id:
            info = ref_by_id[clean_id]
            match_type = "编号精确匹配"
            match_id = clean_id
            match_name = info.get(ref_name_col, "")
            match_parent = info.get(ref_parent_col, "")
            matched = True

        if not matched and clean_name:
            best_score = 0
            best_info = None
            for rname, infos in ref_by_name.items():
                score = fuzz.ratio(clean_name, rname)
                if score > best_score and score >= threshold:
                    best_score = score
                    best_info = infos[0]
            if best_info:
                match_type = f"名称模糊匹配(得分{best_score})"
                match_id = best_info.get(ref_id_col, "")
                match_name = best_info.get(ref_name_col, "")
                match_parent = best_info.get(ref_parent_col, "")
                matched = True

        if not matched and clean_parent:
            if clean_parent in ref_by_id:
                match_type = "上级编号匹配（推测）"
                match_id = ""
                match_name = clean_name
                match_parent = clean_parent
                matched = True

        if matched:
            result_df.at[idx, "匹配类型"] = match_type
            result_df.at[idx, "匹配到的编号"] = match_id
            result_df.at[idx, "匹配到的名称"] = match_name
            result_df.at[idx, "匹配到的上级编号"] = match_parent
        else:
            result_df.at[idx, "匹配类型"] = "未匹配"

    return result_df

# ---------- 主程序 ----------
class ToolApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Excel 小工具集")
        self.root.geometry("900x720")
        self.root.minsize(820, 660)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.create_weeks_tab()
        self.create_sessions_tab()
        self.create_excel_split_tab()
        self.create_excel_merge_tab()
        self.create_excel_info_tab()
        self.create_clean_tab()  # 新增

    # ---------- 原有标签页（不变）----------
    def create_weeks_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="周次展开")
        ttk.Label(frame, text="请输入周次表达式（每行一条）：").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.weeks_input = ScrolledText(frame, width=100, height=12, wrap="word")
        self.weeks_input.grid(row=1, column=0, columnspan=2, padx=8, pady=4, sticky="nsew")
        self.weeks_input.insert("1.0", "2-4周\n6周\n2-16周(双)\n2-10周(单)\n2周,3周")
        ttk.Button(frame, text="处理并复制", command=self.run_weeks).grid(row=2, column=0, padx=8, pady=8, sticky="w")
        ttk.Button(frame, text="清空", command=lambda: self.weeks_input.delete("1.0", "end")).grid(row=2, column=1, padx=8, pady=8, sticky="w")
        ttk.Label(frame, text="结果预览：").grid(row=3, column=0, sticky="w", padx=8, pady=(8, 4))
        self.weeks_output = ScrolledText(frame, width=100, height=10, wrap="word")
        self.weeks_output.grid(row=4, column=0, columnspan=2, padx=8, pady=4, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)

    def run_weeks(self):
        lines = [line.strip() for line in self.weeks_input.get("1.0", "end").splitlines() if line.strip()]
        if not lines:
            messagebox.showwarning("提示", "请输入内容后再处理。")
            return
        processed = [expand_weeks(line) for line in lines]
        output_text = "\n".join(processed)
        self.weeks_output.delete("1.0", "end")
        self.weeks_output.insert("1.0", output_text)
        copy_to_clipboard(output_text)
        messagebox.showinfo("完成", "处理结果已复制到剪贴板。")

    def create_sessions_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="节次展开")
        ttk.Label(frame, text="请输入星期和节次（例如：3 1-8节，每行一条）：").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.sessions_input = ScrolledText(frame, width=100, height=12, wrap="word")
        self.sessions_input.grid(row=1, column=0, columnspan=2, padx=8, pady=4, sticky="nsew")
        self.sessions_input.insert("1.0", "3 1-8节\n2 1-3节,5-6节")
        ttk.Button(frame, text="处理并复制", command=self.run_sessions).grid(row=2, column=0, padx=8, pady=8, sticky="w")
        ttk.Button(frame, text="清空", command=lambda: self.sessions_input.delete("1.0", "end")).grid(row=2, column=1, padx=8, pady=8, sticky="w")
        ttk.Label(frame, text="结果预览：").grid(row=3, column=0, sticky="w", padx=8, pady=(8, 4))
        self.sessions_output = ScrolledText(frame, width=100, height=10, wrap="word")
        self.sessions_output.grid(row=4, column=0, columnspan=2, padx=8, pady=4, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)

    def run_sessions(self):
        lines = [line.strip() for line in self.sessions_input.get("1.0", "end").splitlines() if line.strip()]
        if not lines:
            messagebox.showwarning("提示", "请输入内容后再处理。")
            return
        output_lines = []
        for line in lines:
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            week_num_str, session_str = parts
            try:
                week_num = int(week_num_str)
                expanded = expand_sessions(week_num, session_str)
                output_lines.append(",".join(expanded))
            except ValueError:
                continue
        if not output_lines:
            messagebox.showwarning("提示", "没有生成有效结果。")
            return
        output_text = "\n".join(output_lines)
        self.sessions_output.delete("1.0", "end")
        self.sessions_output.insert("1.0", output_text)
        copy_to_clipboard(output_text)
        messagebox.showinfo("完成", "处理结果已复制到剪贴板。")

    def create_excel_split_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Excel 拆分")
        ttk.Label(frame, text="Excel 文件：").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.excel_path_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.excel_path_var, width=70).grid(row=0, column=1, padx=8, pady=(8, 4), sticky="ew")
        ttk.Button(frame, text="选择文件", command=self.choose_excel_file).grid(row=0, column=2, padx=8, pady=(8, 4))
        ttk.Label(frame, text="每个文件最多行数：").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.rows_var = tk.StringVar(value="2000")
        ttk.Entry(frame, textvariable=self.rows_var, width=20).grid(row=1, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(frame, text="输出格式：").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.format_var = tk.StringVar(value="xlsx")
        ttk.Combobox(frame, textvariable=self.format_var, values=["xlsx", "xls"], state="readonly", width=18).grid(row=2, column=1, sticky="w", padx=8, pady=4)
        ttk.Button(frame, text="开始拆分", command=self.run_excel_split).grid(row=3, column=0, padx=8, pady=10, sticky="w")
        ttk.Label(frame, text="处理结果：").grid(row=4, column=0, sticky="nw", padx=8, pady=(8, 4))
        self.excel_output = ScrolledText(frame, width=100, height=16, wrap="word")
        self.excel_output.grid(row=5, column=0, columnspan=3, padx=8, pady=4, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

    def choose_excel_file(self):
        path = filedialog.askopenfilename(filetypes=[("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")])
        if path:
            self.excel_path_var.set(path)

    def run_excel_split(self):
        file_path = self.excel_path_var.get().strip()
        if not file_path:
            messagebox.showwarning("提示", "请先选择 Excel 文件。")
            return
        try:
            rows_per_file = int(self.rows_var.get().strip())
        except ValueError:
            messagebox.showwarning("提示", "每个文件最多行数请输入整数。")
            return
        try:
            output_files, summary = split_excel_by_rows(file_path, rows_per_file=rows_per_file, output_format=self.format_var.get())
        except Exception as exc:
            messagebox.showerror("错误", f"处理失败：{exc}")
            return
        log_lines = [
            f"源文件：{summary['source_file']}",
            f"总数据行数：{summary['total_rows']}",
            f"每个文件最多行数：{summary['rows_per_file']}",
            f"共拆分为：{summary['output_count']} 个文件",
        ]
        for part_num, start_row, end_row, row_count, output_file in summary['details']:
            log_lines.append(f"第 {part_num} 个文件：{output_file}，{row_count} 条（{start_row}-{end_row}）")
        self.excel_output.delete("1.0", "end")
        self.excel_output.insert("1.0", "\n".join(log_lines))
        messagebox.showinfo("完成", f"已生成 {summary['output_count']} 个文件。")

    def create_excel_merge_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Excel 合并")
        ttk.Label(frame, text="合并方式：").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.merge_mode_var = tk.StringVar(value="files")
        ttk.Combobox(frame, textvariable=self.merge_mode_var, values=[("多个 Excel 文件合并", "files"), ("单个 Excel 文件多个 sheet 合并", "sheets")], state="readonly", width=30).grid(row=0, column=1, sticky="w", padx=8, pady=(8, 4))
        ttk.Label(frame, text="输入文件：").grid(row=1, column=0, sticky="nw", padx=8, pady=(8, 4))
        self.merge_input_text = ScrolledText(frame, width=100, height=8, wrap="word")
        self.merge_input_text.grid(row=1, column=1, columnspan=2, padx=8, pady=4, sticky="nsew")
        ttk.Button(frame, text="选择文件", command=self.choose_merge_files).grid(row=2, column=0, padx=8, pady=8, sticky="w")
        ttk.Button(frame, text="开始合并", command=self.run_merge).grid(row=2, column=1, padx=8, pady=8, sticky="w")
        ttk.Label(frame, text="输出结果：").grid(row=3, column=0, sticky="nw", padx=8, pady=(8, 4))
        self.merge_output = ScrolledText(frame, width=100, height=14, wrap="word")
        self.merge_output.grid(row=4, column=0, columnspan=3, padx=8, pady=4, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)

    def choose_merge_files(self):
        mode = self.merge_mode_var.get()
        if mode == "files":
            paths = filedialog.askopenfilenames(filetypes=[("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")])
            if paths:
                self.merge_input_text.delete("1.0", "end")
                self.merge_input_text.insert("1.0", "\n".join(paths))
        else:
            path = filedialog.askopenfilename(filetypes=[("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")])
            if path:
                self.merge_input_text.delete("1.0", "end")
                self.merge_input_text.insert("1.0", path)

    def run_merge(self):
        mode = self.merge_mode_var.get()
        raw_text = self.merge_input_text.get("1.0", "end").strip()
        if not raw_text:
            messagebox.showwarning("提示", "请先选择文件。")
            return
        if mode == "files":
            file_paths = [p.strip() for p in raw_text.splitlines() if p.strip()]
            if len(file_paths) < 2:
                messagebox.showwarning("提示", "请至少选择 2 个 Excel 文件。")
                return
            output_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel 文件", "*.xlsx")])
            if not output_path:
                return
            try:
                result_path = merge_excel_files(file_paths, output_path)
            except Exception as exc:
                messagebox.showerror("错误", f"合并失败：{exc}")
                return
            self.merge_output.delete("1.0", "end")
            self.merge_output.insert("1.0", f"已生成合并文件：{result_path}\n合并前已校验列标题一致。")
            messagebox.showinfo("完成", "Excel 文件合并完成。")
        else:
            file_path = raw_text
            output_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel 文件", "*.xlsx")])
            if not output_path:
                return
            try:
                result_path = merge_excel_sheets(file_path, output_path)
            except Exception as exc:
                messagebox.showerror("错误", f"合并失败：{exc}")
                return
            self.merge_output.delete("1.0", "end")
            self.merge_output.insert("1.0", f"已生成合并文件：{result_path}\n合并前已校验列标题一致。")
            messagebox.showinfo("完成", "工作表合并完成。")

    def create_excel_info_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Excel 信息")
        ttk.Label(frame, text="Excel 文件：").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.info_path_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.info_path_var, width=70).grid(row=0, column=1, padx=8, pady=(8, 4), sticky="ew")
        ttk.Button(frame, text="选择文件", command=self.choose_info_file).grid(row=0, column=2, padx=8, pady=(8, 4))
        ttk.Button(frame, text="查看信息", command=self.run_excel_info).grid(row=1, column=0, padx=8, pady=8, sticky="w")
        ttk.Label(frame, text="摘要信息：").grid(row=2, column=0, sticky="nw", padx=8, pady=(8, 4))
        self.info_output = ScrolledText(frame, width=100, height=20, wrap="word")
        self.info_output.grid(row=3, column=0, columnspan=3, padx=8, pady=4, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

    def choose_info_file(self):
        path = filedialog.askopenfilename(filetypes=[("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")])
        if path:
            self.info_path_var.set(path)

    def run_excel_info(self):
        file_path = self.info_path_var.get().strip()
        if not file_path:
            messagebox.showwarning("提示", "请先选择 Excel 文件。")
            return
        try:
            summary = get_excel_summary(file_path)
        except Exception as exc:
            messagebox.showerror("错误", f"读取失败：{exc}")
            return
        self.info_output.delete("1.0", "end")
        self.info_output.insert("1.0", summary)

    # ---------- 新增：数据清洗标签页（优化布局）----------
    def create_clean_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="数据清洗（通用匹配）")

        # 文件选择行
        ttk.Label(frame, text="待清洗文件：").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.clean_file_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.clean_file_var, width=60).grid(row=0, column=1, padx=8, pady=(8, 4), sticky="ew")
        ttk.Button(frame, text="选择", command=lambda: self._choose_file(self.clean_file_var)).grid(row=0, column=2, padx=8, pady=(8, 4))

        ttk.Label(frame, text="匹配参考文件：").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.ref_file_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.ref_file_var, width=60).grid(row=1, column=1, padx=8, pady=4, sticky="ew")
        ttk.Button(frame, text="选择", command=lambda: self._choose_file(self.ref_file_var)).grid(row=1, column=2, padx=8, pady=4)

        # 待清洗表列名（单独成行，三个字段水平排列）
        ttk.Label(frame, text="待清洗表列名：").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        # 使用子框架将三个输入框放在同一行
        subframe_clean = ttk.Frame(frame)
        subframe_clean.grid(row=2, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Label(subframe_clean, text="编号列:").pack(side="left", padx=(0,4))
        self.clean_id_col = tk.StringVar(value="地点号")
        ttk.Entry(subframe_clean, textvariable=self.clean_id_col, width=12).pack(side="left", padx=(0,15))
        ttk.Label(subframe_clean, text="名称列:").pack(side="left", padx=(0,4))
        self.clean_name_col = tk.StringVar(value="地点名称")
        ttk.Entry(subframe_clean, textvariable=self.clean_name_col, width=12).pack(side="left", padx=(0,15))
        ttk.Label(subframe_clean, text="上级列:").pack(side="left", padx=(0,4))
        self.clean_parent_col = tk.StringVar(value="上级地点")
        ttk.Entry(subframe_clean, textvariable=self.clean_parent_col, width=12).pack(side="left")

        # 匹配参考表列名（单独成行）
        ttk.Label(frame, text="匹配参考表列名：").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        subframe_ref = ttk.Frame(frame)
        subframe_ref.grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Label(subframe_ref, text="编号列:").pack(side="left", padx=(0,4))
        self.ref_id_col = tk.StringVar(value="FJBH")
        ttk.Entry(subframe_ref, textvariable=self.ref_id_col, width=12).pack(side="left", padx=(0,15))
        ttk.Label(subframe_ref, text="名称列:").pack(side="left", padx=(0,4))
        self.ref_name_col = tk.StringVar(value="FJMC")
        ttk.Entry(subframe_ref, textvariable=self.ref_name_col, width=12).pack(side="left", padx=(0,15))
        ttk.Label(subframe_ref, text="上级列:").pack(side="left", padx=(0,4))
        self.ref_parent_col = tk.StringVar(value="LCBH")
        ttk.Entry(subframe_ref, textvariable=self.ref_parent_col, width=12).pack(side="left")

        # 模糊匹配阈值（带数值显示）
        ttk.Label(frame, text="模糊匹配阈值：").grid(row=4, column=0, sticky="w", padx=8, pady=4)
        threshold_frame = ttk.Frame(frame)
        threshold_frame.grid(row=4, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        self.threshold_var = tk.IntVar(value=80)
        self.threshold_label = ttk.Label(threshold_frame, text="80")
        self.threshold_label.pack(side="left", padx=(0,10))
        scale = ttk.Scale(threshold_frame, from_=50, to=100, orient="horizontal", variable=self.threshold_var, length=200)
        scale.pack(side="left")
        # 绑定滑动事件更新数值显示
        def update_threshold_label(*args):
            self.threshold_label.config(text=str(self.threshold_var.get()))
        self.threshold_var.trace('w', update_threshold_label)

        # 开始按钮
        ttk.Button(frame, text="开始清洗", command=self.run_clean).grid(row=5, column=0, padx=8, pady=10, sticky="w")

        # 日志输出
        ttk.Label(frame, text="处理日志：").grid(row=6, column=0, sticky="nw", padx=8, pady=(8, 4))
        self.clean_log = ScrolledText(frame, width=100, height=16, wrap="word")
        self.clean_log.grid(row=7, column=0, columnspan=3, padx=8, pady=4, sticky="nsew")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)

    def _choose_file(self, var):
        path = filedialog.askopenfilename(filetypes=[("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")])
        if path:
            var.set(path)

    def run_clean(self):
        clean_path = self.clean_file_var.get().strip()
        ref_path = self.ref_file_var.get().strip()
        if not clean_path or not ref_path:
            messagebox.showwarning("提示", "请选择待清洗文件和匹配参考文件。")
            return

        try:
            clean_df = pd.read_excel(clean_path, engine='openpyxl')
            ref_df = pd.read_excel(ref_path, engine='openpyxl')
        except Exception as e:
            messagebox.showerror("错误", f"读取文件失败：{e}")
            return

        clean_id = self.clean_id_col.get().strip()
        clean_name = self.clean_name_col.get().strip()
        clean_parent = self.clean_parent_col.get().strip()
        ref_id = self.ref_id_col.get().strip()
        ref_name = self.ref_name_col.get().strip()
        ref_parent = self.ref_parent_col.get().strip()

        missing_clean = [c for c in [clean_id, clean_name, clean_parent] if c not in clean_df.columns]
        missing_ref = [c for c in [ref_id, ref_name, ref_parent] if c not in ref_df.columns]
        if missing_clean:
            messagebox.showerror("错误", f"待清洗表缺少列：{missing_clean}")
            return
        if missing_ref:
            messagebox.showerror("错误", f"匹配参考表缺少列：{missing_ref}")
            return

        threshold = self.threshold_var.get()

        self.clean_log.delete("1.0", "end")
        self.clean_log.insert("1.0", "正在匹配，请稍候...\n")
        self.root.update()

        try:
            result_df = clean_data_with_ref(
                clean_df, ref_df,
                clean_id, clean_name, clean_parent,
                ref_id, ref_name, ref_parent,
                threshold
            )
        except Exception as e:
            messagebox.showerror("错误", f"匹配过程出错：{e}")
            return

        base_name = os.path.splitext(os.path.basename(clean_path))[0]
        report_name = f"{base_name}_清洗报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        report_path = os.path.join(os.path.dirname(clean_path), report_name)
        try:
            with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
                result_df.to_excel(writer, sheet_name="匹配结果", index=False)
                stats = result_df["匹配类型"].value_counts().reset_index()
                stats.columns = ["匹配类型", "数量"]
                stats.to_excel(writer, sheet_name="匹配统计", index=False)
                unmatched = result_df[result_df["匹配类型"] == "未匹配"]
                unmatched.to_excel(writer, sheet_name="未匹配清单", index=False)
        except Exception as e:
            messagebox.showerror("错误", f"生成报告失败：{e}")
            return

        log_text = f"匹配完成！报告已生成：{report_path}\n\n匹配统计：\n"
        for _, row in stats.iterrows():
            log_text += f"  {row['匹配类型']}: {row['数量']} 条\n"
        self.clean_log.delete("1.0", "end")
        self.clean_log.insert("1.0", log_text)
        messagebox.showinfo("完成", f"清洗完成，报告保存在：{report_path}")


def main():
    root = tk.Tk()
    ToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()