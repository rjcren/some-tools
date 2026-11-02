# -*- coding: utf-8 -*-
"""
视频时长统计工具  v3
  - 多编码尝试 + 汉字投票
  - 全程日志落盘，不依赖弹窗
  - 顶部 FORCE_ENCODING 可强制指定编码

  共需要选择三次文件，
  第一次选择数据库查询结果，sql见下文，将结果复制到txt或csv
  第二次选择视频所在根目录（即 pic 文件夹），
  第三次选择保存统计结果的 CSV 文件。

  python 3.12
  numpy<2.4

获取视频文件列表及路径的 SQL
select ztbz ztbzbh,
       (select sbdw from ks_tkb where gid = k.sstk) sstk,
       (case ztbz
         when '00' then
          '待审核'
         when '99' then
          '审核通过'
         when '91' then
          '审核退回'
         else
          '未提交'
       end) ztbz,
       gid,
       wdbh,
       filename,
       path,
       wdlx,
       (select '(' || rygh || ')' || xm from gx_sys_ryb where rybh = jdr) jdr,
       to_char(jdrq, 'yyyy-mm-dd') as jdrq
  from pt_sys_aqspb k
 where 1 = 1
   and k.ztbz in ('00', '99', '91')
 order by WDBH desc
"""
import os
import sys
import csv
import struct
import tempfile
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

# ============================================================
VERSION = 'v3-2026-10-30'          # ← 每次改代码请递增
OUTPUT_ENCODING = 'gb18030'        # CSV 输出编码：'gb18030' 或 'utf-8-sig'
FORCE_ENCODING = None              # None=自动；或强制 'gbk' / 'utf-8-sig' / 'utf-8'
# ============================================================

VIDEO_EXTS = ('.mp4', '.m4v', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.ts')
LOG_FILE = os.path.join(tempfile.gettempdir(), '视频时长统计_运行日志.txt')


def log(msg):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.datetime.now().strftime("%H:%M:%S")}] [{VERSION}] {msg}\n')
    except Exception:
        pass


def fmt_duration(seconds):
    if seconds is None:
        return ""
    t = int(round(seconds))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def count_cjk(text):
    return sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')


# ---------------- MP4 时长解析 ----------------
def _find_box(f, start, end, target):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            return None
        size = struct.unpack('>I', hdr[0:4])[0]
        btype = hdr[4:8]
        hsize = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return None
            size = struct.unpack('>Q', ext)[0]
            hsize = 16
        elif size == 0:
            size = end - pos
        if size < hsize:
            return None
        if btype == target:
            return pos, size, hsize
        pos += size
    return None


def get_mp4_duration(path):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            fsize = f.tell()
            moov = _find_box(f, 0, fsize, b'moov')
            if not moov:
                return None
            mp, ms, mh = moov
            mvhd = _find_box(f, mp + mh, mp + ms, b'mvhd')
            if not mvhd:
                return None
            vp, _, vh = mvhd
            f.seek(vp + vh)
            version = struct.unpack('>B', f.read(1))[0]
            f.read(3)
            if version == 1:
                f.read(16)
                ts = struct.unpack('>I', f.read(4))[0]
                dur = struct.unpack('>Q', f.read(8))[0]
            else:
                f.read(8)
                ts = struct.unpack('>I', f.read(4))[0]
                dur = struct.unpack('>I', f.read(4))[0]
            if ts == 0:
                return None
            return dur / ts
    except Exception as e:
        log(f'  MP4 解析异常: {path} -> {e}')
        return None


def get_duration(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.mp4', '.m4v', '.mov'):
        return get_mp4_duration(path)
    return None


# ---------------- 数据库读取（核心修复） ----------------
def parse_db_file(db_file):
    log(f'读取数据库文件: {db_file}')
    with open(db_file, 'rb') as f:
        raw = f.read()
    log(f'  文件大小: {len(raw)} 字节')
    log(f'  前 32 字节 hex: {raw[:32].hex()}')
    log(f'  UTF-8 BOM: {raw.startswith(bytes([0xef, 0xbb, 0xbf]))}')

    # 多编码尝试
    attempts = {}
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'gb18030'):
        try:
            text = raw.decode(enc)
            cjk = count_cjk(text)
            attempts[enc] = {'ok': True, 'text': text, 'cjk': cjk}
            log(f'  [{enc}] 成功, 汉字数={cjk}')
        except UnicodeDecodeError as e:
            attempts[enc] = {'ok': False, 'err': str(e)}
            log(f'  [{enc}] 失败: {e}')

    # 写详细诊断文件
    diag_path = os.path.join(os.path.dirname(db_file) or '.', '调试_编码检测.txt')
    try:
        with open(diag_path, 'w', encoding='utf-8') as f:
            f.write(f'版本: {VERSION}\n')
            f.write(f'文件: {db_file}\n')
            f.write(f'大小: {len(raw)} 字节\n')
            f.write(f'前 32 字节 hex: {raw[:32].hex()}\n')
            f.write(f'UTF-8 BOM: {raw.startswith(bytes([0xef, 0xbb, 0xbf]))}\n\n')
            for enc, info in attempts.items():
                f.write(f'===== 编码 {enc} =====\n')
                if info['ok']:
                    f.write(f'结果: 成功，汉字数={info["cjk"]}\n')
                    first = info['text'].split('\n')[0][:300]
                    f.write(f'首行: {first}\n')
                else:
                    f.write(f'结果: 失败\n错误: {info["err"]}\n')
                f.write('\n')
        log(f'  诊断文件已写: {diag_path}')
    except Exception as e:
        log(f'  写诊断文件失败: {e}')

    # 选择编码
    valid = {k: v for k, v in attempts.items() if v['ok']}
    if not valid:
        raise RuntimeError(f'所有编码都解码失败，请打开 {diag_path} 查看详情')

    if FORCE_ENCODING and FORCE_ENCODING in valid:
        best_enc = FORCE_ENCODING
        log(f'  >>> 使用强制编码: {best_enc}')
    else:
        cjk_ok = {k: v for k, v in valid.items() if v['cjk'] > 0}
        if cjk_ok:
            best_enc = max(cjk_ok, key=lambda k: cjk_ok[k]['cjk'])
        elif raw.startswith(bytes([0xef, 0xbb, 0xbf])) and 'utf-8-sig' in valid:
            best_enc = 'utf-8-sig'
        elif 'utf-8' in valid:
            best_enc = 'utf-8'
        else:
            best_enc = list(valid.keys())[0]
        log(f'  >>> 自动选择编码: {best_enc}')

    text = valid[best_enc]['text']

    rows = []
    for line in text.splitlines():
        line = line.rstrip('\r\n')
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 8:
            continue
        idx, cat, fname, fpath = parts[0], parts[2], parts[6], parts[7]
        if not fpath.lower().endswith(VIDEO_EXTS):
            continue
        rows.append((idx, cat, fname, fpath))

    log(f'  解析到 {len(rows)} 条视频记录')
    if rows:
        log(f'  前 3 条预览:')
        for r in rows[:3]:
            log(f'    {r[0]} | {r[1]} | {r[2]}')
    return rows, best_enc


def map_to_local(base_dir, db_path):
    rel = db_path.lstrip('/\\').replace('/', os.sep).replace('\\', os.sep)
    return os.path.join(base_dir, rel)


# ---------------- 主流程 ----------------
def main():
    log(f'========== 程序启动 {VERSION} ==========')

    root = tk.Tk()
    root.withdraw()

    db_file = filedialog.askopenfilename(
        title='请选择数据库导出文件（txt / csv）',
        filetypes=[('文本文件', '*.txt'), ('CSV 文件', '*.csv'), ('所有文件', '*.*')]
    )
    if not db_file:
        log('用户取消选择数据库文件')
        return
    log(f'用户选择数据库: {db_file}')

    base_dir = filedialog.askdirectory(title='请选择视频所在根目录（例如 pic 文件夹）')
    if not base_dir:
        log('用户取消选择根目录')
        return
    log(f'用户选择根目录: {base_dir}')

    try:
        records, used_enc = parse_db_file(db_file)
    except Exception as e:
        log(f'解析失败: {e}')
        messagebox.showerror('解析失败', str(e))
        return

    if not records:
        messagebox.showerror('错误', '未解析到任何有效视频记录，详见日志')
        log('未解析到有效记录')
        return

    results = []
    ok_cnt = miss_cnt = fail_cnt = 0
    total_sec = 0.0

    for idx, cat, fname, fpath in records:
        abs_path = map_to_local(base_dir, fpath)
        if not os.path.isfile(abs_path):
            miss_cnt += 1
            results.append([idx, cat, fname, fpath, '文件缺失', '', '', abs_path])
            continue
        dur = get_duration(abs_path)
        if dur is None:
            fail_cnt += 1
            results.append([idx, cat, fname, fpath, '读取失败', '', '', abs_path])
        else:
            ok_cnt += 1
            total_sec += dur
            results.append([idx, cat, fname, fpath, '成功',
                            f'{dur:.2f}', fmt_duration(dur), abs_path])

    log(f'统计完成: 总数={len(results)} 成功={ok_cnt} 缺失={miss_cnt} 失败={fail_cnt} '
        f'总时长={fmt_duration(total_sec)}')

    out_path = filedialog.asksaveasfilename(
        title='保存统计结果',
        defaultextension='.csv',
        initialfile=f'视频时长统计_{VERSION}.csv',       # ← 文件名带版本号
        filetypes=[('CSV 文件', '*.csv')]
    )
    if out_path:
        try:
            with open(out_path, 'w', encoding=OUTPUT_ENCODING, newline='') as f:
                w = csv.writer(f)
                w.writerow(['序号', '分类', '文件名', '相对路径',
                            '状态', '时长（秒）', '时长（时:分:秒）', '绝对路径'])
                for r in results:
                    w.writerow(r)
                w.writerow([])
                # 尾部写版本和诊断信息，不依赖弹窗
                w.writerow(['【版本】', VERSION])
                w.writerow(['【读取编码】', used_enc])
                w.writerow(['【CSV输出编码】', OUTPUT_ENCODING])
                w.writerow(['【统计汇总】', f'总记录数:{len(results)}',
                            f'成功:{ok_cnt}', f'缺失:{miss_cnt}',
                            f'失败:{fail_cnt}',
                            f'{total_sec:.2f}', fmt_duration(total_sec), ''])
            log(f'CSV 已保存: {out_path}')
        except Exception as e:
            log(f'CSV 保存失败: {e}')
            messagebox.showerror('保存失败', str(e))
            return

    msg = (
        f'版本：{VERSION}\n'
        f'数据库读取编码：{used_enc}\n'
        f'CSV 输出编码：{OUTPUT_ENCODING}\n\n'
        f'总记录数：{len(results)}\n'
        f'成功：{ok_cnt}   缺失：{miss_cnt}   失败：{fail_cnt}\n'
        f'总时长：{fmt_duration(total_sec)}\n\n'
        f'结果文件：\n{out_path or "（未保存）"}\n\n'
        f'日志：\n{LOG_FILE}'
    )
    messagebox.showinfo(f'完成 {VERSION}', msg)
    log('程序正常结束')
    root.destroy()


if __name__ == '__main__':
    main()