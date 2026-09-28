#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegraph-epub-converter.py
====================================================
telegra.ph 漫画网页一键转 EPUB 电子书工具（tkinter GUI + CLI，支持批量）

功能：
  1. 支持本地 HTML 网页保存文件（无扩展名 / .html / .htm 均可自动识别）
  2. 支持 telegra.ph 在线链接（自动下载页面 HTML 与全部漫画图片）
  3. 解析 HTML 提取漫画原图（保持清晰度），按页面顺序逐页排版生成漫画版 EPUB
     （每页一图 + 封面 + 目录导航 + 书脊导航 + 结构校验）
  4. 纯标准库实现：urllib 下载、zipfile 手写 EPUB3（OPF/XHTML/NCX），零第三方依赖
  5. 批量转换：
     - GUI：输入列表支持添加多条（文件多选 / 在线链接 / 扫描文件夹），
            可增删、清空，逐个转换并汇总成功 / 失败 / 取消结果
     - CLI：--cli 后接多个输入参数，或 --dir 扫描文件夹内所有 Telegraph 网页文件
  6. 并发下载图片：ThreadPoolExecutor 多线程，默认 16 路并发（--jobs / GUI 可调 1-64），
     下载完成后按页面顺序写入 EPUB，图片顺序稳定
  7. 暂停 / 继续：GUI 按钮一键暂停下载与打包、随时继续；CLI 按 Ctrl+Break 切换暂停
  8. 取消：GUI 按钮一键取消当前及后续任务；CLI 按 Ctrl+C 优雅取消。
     取消后自动清理临时文件：已完成的转换保留输出，未完成的标记为"已取消"

用法：
  * 双击脚本 → 弹出 GUI，通过"添加文件 / 添加链接 / 添加文件夹"建立输入列表后批量转换；
    转换中可用"暂停/继续"与"取消"按钮控制
  * 命令行（无界面）：
      单输入  : python telegraph-epub-converter.py --cli <本地路径或在线链接> [--out <输出目录>] [--title <书名>] [--jobs <1-64>]
      多输入  : python telegraph-epub-converter.py --cli <输入1> <输入2> ... [--out <输出目录>]
      扫文件夹: python telegraph-epub-converter.py --cli --dir <文件夹> [--out <输出目录>]
      组合    : python telegraph-epub-converter.py --cli <输入1> --dir <文件夹> ... [--out <输出目录>]
    转换中：Ctrl+C 取消，Ctrl+Break 暂停/继续（Windows）
"""

import os
import re
import sys
import time
import socket
import html as html_mod
import urllib.request
from urllib.error import URLError
import datetime
import zipfile
import threading
import queue
import tempfile
import shutil
import signal
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    TK_AVAILABLE = True
except Exception:  # pragma: no cover - 无显示环境
    TK_AVAILABLE = False

# ---------------------------------------------------------------- 常量

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
TIMEOUT = 60
IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
DEFAULT_CONCURRENCY = 16      # 默认并发下载线程数
MAX_CONCURRENCY = 64         # 并发数上限
MIN_CONCURRENCY = 1


class DownloadCancelledError(Exception):
    """用户取消转换时抛出"""


# ---------------------------------------------------------------- 控制辅助

def wait_resume(pause_event, cancel_event):
    """等待暂停解除（可被取消中断）。暂停期间轮询，取消信号可立即生效。"""
    while pause_event is not None and not pause_event.is_set():
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelledError("用户已取消")
        time.sleep(0.2)


def check_control(pause_event, cancel_event):
    """下载 / 打包循环中的暂停与取消检查点"""
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelledError("用户已取消")
    wait_resume(pause_event, cancel_event)


# ---------------------------------------------------------------- 网络 / 解析

def log(msg):
    """CLI 模式日志输出"""
    try:
        sys.stdout.write(str(msg) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def fetch(url, timeout=TIMEOUT, retries=3):
    """下载 URL 内容（bytes）。瞬时网络错误自动重试（默认 3 次，逐步退避），最终失败抛出最后一次异常"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except DownloadCancelledError:
            raise
        except (URLError, OSError, socket.timeout) as e:
            last_err = e
            if attempt < retries:
                time.sleep(0.3 * attempt)
    raise last_err


def decode_html(data):
    """按常见编码解码网页 HTML"""
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def guess_title_from_url(url):
    """从 telegra.ph 链接推断书名"""
    m = re.search(r"telegra\.ph/([^/?#]+)", url)
    if m:
        return m.group(1).replace("-", " ").strip() or "Telegraph Manga"
    return "Telegraph Manga"


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(name)).strip()
    name = name.strip(" .")
    return name[:100] or "output"


def extract_image_urls(html_text):
    """按出现顺序提取 HTML 中的漫画图片 URL（telegra.ph 原图）"""
    urls = re.findall(r'<img[^>]*src="(https?://[^"]+)"', html_text, re.I)
    seen, out = set(), []
    for u in urls:
        u = html_mod.unescape(u)
        if u in seen:
            continue
        seen.add(u)
        if re.search(r"\.(jpe?g|png|gif|webp|avif)(\?|$)", u, re.I) or "telegra.ph" in u:
            out.append(u)
    return out


def download_image(url, dest):
    """下载单张图片到本地，返回字节数"""
    data = fetch(url)
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


def resolve_input(raw):
    """识别输入：在线链接 or 本地路径（自动补 .html/.htm）"""
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        raise ValueError("输入为空，请粘贴 telegra.ph 链接或本地文件路径")
    if raw.lower().startswith(("http://", "https://")):
        return "url", raw, None
    p = os.path.abspath(os.path.expanduser(raw))
    for candidate in (p, p + ".html", p + ".htm"):
        if os.path.isfile(candidate):
            return "file", None, candidate
    raise ValueError("本地文件不存在（已尝试原路径 / .html / .htm）：" + p)


def load_html(src_type, url, file_path):
    """读取页面 HTML 文本"""
    if src_type == "url":
        return decode_html(fetch(url))
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------- 并发下载

def download_images_concurrently(img_urls, tmp_dir, concurrency=DEFAULT_CONCURRENCY,
                                 progress_cb=None, pause_event=None, cancel_event=None):
    """并发下载全部图片，返回按页面顺序排列的本地路径列表。

    - 使用 ThreadPoolExecutor 滑动窗口调度，并发数 = concurrency（1-64）
    - 下载结果按原顺序放入 img_paths，保证 EPUB 页面顺序稳定
    - 暂停：pause_event 未设置时阻塞等待（可被取消中断）
    - 取消：cancel_event 设置时取消未启动任务并抛出 DownloadCancelledError
    - 任一张图片失败：取消其余未完成任务并抛出原始异常（由上层记录失败）
    """
    total = len(img_urls)
    if total == 0:
        return []

    exts = []
    for u in img_urls:
        ext = os.path.splitext(u.split("?")[0])[1].lower() or ".jpg"
        if ext not in IMG_EXTS:
            ext = ".jpg"
        exts.append(ext)

    def dest_path(i):
        return os.path.join(tmp_dir, "page_%03d%s" % (i, exts[i - 1]))

    img_paths = [None] * total
    next_idx = 0
    futures = {}
    done = 0
    pool = ThreadPoolExecutor(max_workers=concurrency)

    def submit_next():
        nonlocal next_idx
        if next_idx < total:
            i = next_idx + 1
            fut = pool.submit(download_image, img_urls[i - 1], dest_path(i))
            futures[fut] = i
            next_idx += 1

    cancelled = False
    try:
        for _ in range(min(concurrency, total)):
            submit_next()
        while futures:
            check_control(pause_event, cancel_event)
            finished, _ = wait(futures, return_when=FIRST_COMPLETED, timeout=0.2)
            for f in finished:
                i = futures.pop(f)
                try:
                    size = f.result()
                    if size <= 0:
                        raise RuntimeError("图片 %d 下载失败（0 字节）: %s" % (i, img_urls[i - 1]))
                    img_paths[i - 1] = dest_path(i)
                except DownloadCancelledError:
                    raise
                except Exception:
                    cancelled = True
                    for g in futures:
                        g.cancel()
                    raise
                done += 1
                if progress_cb:
                    progress_cb(6 + int(58.0 * done / total), "下载图片 %d/%d ..." % (done, total))
            while len(futures) < concurrency and next_idx < total:
                submit_next()
    except DownloadCancelledError:
        cancelled = True
        for g in futures:
            g.cancel()
        raise
    finally:
        # 取消/失败时也等待已启动的下载任务结束，确保临时目录可干净清理
        # （cancel_futures=True 会取消未启动任务；运行中的任务让其在当前批内完成）
        if cancelled:
            try:
                pool.shutdown(wait=True, cancel_futures=True)
            except TypeError:  # Python < 3.9
                pool.shutdown(wait=False)
        else:
            pool.shutdown(wait=True)
    return img_paths


# ---------------------------------------------------------------- EPUB 生成（纯标准库）

def media_type(ext):
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "gif": "image/gif", "webp": "image/webp",
    }.get(ext.lstrip(".").lower(), "image/jpeg")


def html_escape(s):
    return html_mod.escape(str(s), quote=True)


def build_page_xhtml(title, page_no, img_src):
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>第 %d 页</title>\n'
        '<style>body{margin:0;padding:0;text-align:center;background:#000;}\n'
        'img{width:100%%;max-width:100%%;height:auto;display:block;margin:0 auto;}</style>\n'
        '</head>\n'
        '<body><div><img src="%s" alt="page %d"/></div></body>\n'
        '</html>\n' % (page_no, img_src, page_no)
    )


def build_ncx(title, epub_id, page_count):
    nav_points = "".join(
        '<navPoint id="p%d" playOrder="%d"><navLabel><text>第 %d 页</text></navLabel>'
        '<content src="page_%03d.xhtml"/></navPoint>' % (i, i, i, i)
        for i in range(1, page_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        '  <head><meta name="dtb:uid" content="%s"/></head>\n'
        '  <docTitle><text>%s</text></docTitle>\n'
        '  <navMap>\n%s\n  </navMap>\n'
        '</ncx>\n' % (html_escape(epub_id), html_escape(title), nav_points)
    )


def build_epub(images, title, out_path, progress_cb=None, pause_event=None, cancel_event=None):
    """手写 EPUB3（含 NCX 兼容老阅读器），逐页排版漫画图片。

    images: 本地图片绝对路径列表（已按页面顺序）
    title : 书名
    out_path: 输出 .epub 路径
    """
    def report(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)
        else:
            log("[%3d%%] %s" % (pct, msg))

    page_count = len(images)
    report(1, "开始打包 EPUB ...")

    # 每张图片的扩展名
    ext_by_path = []
    for p in images:
        ext = os.path.splitext(p)[1].lower() or ".jpg"
        if ext not in IMG_EXTS:
            ext = ".jpg"
        if ext == ".jpeg":
            ext = ".jpg"
        ext_by_path.append(ext)
    cover_ext = ext_by_path[0]

    epub_id = "urn:uuid:" + datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    date_str = datetime.date.today().isoformat()

    file_specs = []  # (arcname, data, compress_type)

    # 1) mimetype 必须第一个且不压缩
    file_specs.append(("mimetype", b"application/epub+zip", zipfile.ZIP_STORED))

    # 2) container.xml
    container_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles>\n'
        '    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>\n'
        '  </rootfiles>\n'
        '</container>\n'
    ).encode("utf-8")
    file_specs.append(("META-INF/container.xml", container_xml, zipfile.ZIP_DEFLATED))

    # 3) 每页 XHTML
    for i, ext in enumerate(ext_by_path, 1):
        check_control(pause_event, cancel_event)
        xhtml = build_page_xhtml(title, i, "images/page_%03d%s" % (i, ext))
        file_specs.append(("EPUB/page_%03d.xhtml" % i, xhtml.encode("utf-8"), zipfile.ZIP_DEFLATED))

    # 4) 封面 XHTML（第一页图片）
    check_control(pause_event, cancel_event)
    cover_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>封面</title>\n'
        '<style>body{margin:0;padding:0;text-align:center;background:#000;}\n'
        'img{width:100%%;max-width:100%%;height:auto;display:block;margin:0 auto;}</style>\n'
        '</head>\n'
        '<body><div><img src="images/cover%s" alt="cover"/></div></body>\n'
        '</html>\n' % cover_ext
    )
    file_specs.append(("EPUB/cover.xhtml", cover_xhtml.encode("utf-8"), zipfile.ZIP_DEFLATED))

    # 5) nav.xhtml（EPUB3 目录导航）
    check_control(pause_event, cancel_event)
    nav_entries = "".join(
        '<li><a href="page_%03d.xhtml">第 %d 页</a></li>' % (i, i)
        for i in range(1, page_count + 1)
    )
    nav_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<head><title>目录</title></head>\n'
        '<body>\n'
        '  <nav epub:type="toc" id="toc">\n'
        '    <h1>%s</h1>\n'
        '    <ol>\n%s\n    </ol>\n'
        '  </nav>\n'
        '</body>\n'
        '</html>\n' % (html_escape(title), nav_entries)
    )
    file_specs.append(("EPUB/nav.xhtml", nav_xhtml.encode("utf-8"), zipfile.ZIP_DEFLATED))

    # 6) toc.ncx（EPUB2 兼容）
    check_control(pause_event, cancel_event)
    file_specs.append(("EPUB/toc.ncx", build_ncx(title, epub_id, page_count).encode("utf-8"),
                       zipfile.ZIP_DEFLATED))

    # 7) content.opf（清单 + 书脊）
    check_control(pause_event, cancel_event)
    manifest_items = []
    manifest_items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    manifest_items.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    manifest_items.append('<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
    for i in range(1, page_count + 1):
        manifest_items.append('<item id="page_%03d" href="page_%03d.xhtml" media-type="application/xhtml+xml"/>'
                              % (i, i))
    manifest_items.append('<item id="cover_img" href="images/cover%s" media-type="%s"/>'
                          % (cover_ext, media_type(cover_ext)))
    for i, ext in enumerate(ext_by_path, 1):
        manifest_items.append('<item id="img_%03d" href="images/page_%03d%s" media-type="%s"/>'
                              % (i, i, ext, media_type(ext)))

    spine_items = ['<itemref idref="cover"/>'] + \
                  ['<itemref idref="page_%03d"/>' % i for i in range(1, page_count + 1)]

    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang="zh">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">%s</dc:identifier>\n'
        '    <dc:title>%s</dc:title>\n'
        '    <dc:language>zh</dc:language>\n'
        '    <dc:date>%s</dc:date>\n'
        '    <meta property="dcterms:modified">%sT00:00:00Z</meta>\n'
        '  </metadata>\n'
        '  <manifest>\n%s\n  </manifest>\n'
        '  <spine toc="ncx">\n%s\n  </spine>\n'
        '  <guide>\n    <reference type="cover" title="封面" href="cover.xhtml"/>\n  </guide>\n'
        '</package>\n' % (
            html_escape(epub_id), html_escape(title), date_str, date_str,
            "\n".join("    " + m for m in manifest_items),
            "\n".join("    " + s for s in spine_items),
        )
    )
    file_specs.append(("EPUB/content.opf", opf.encode("utf-8"), zipfile.ZIP_DEFLATED))

    # 8) 图片文件
    report(10, "写入页面与图片文件 ...")
    for i, (img_path, ext) in enumerate(zip(images, ext_by_path), 1):
        check_control(pause_event, cancel_event)
        with open(img_path, "rb") as f:
            file_specs.append(("EPUB/images/page_%03d%s" % (i, ext), f.read(), zipfile.ZIP_DEFLATED))
    check_control(pause_event, cancel_event)
    with open(images[0], "rb") as f:
        file_specs.append(("EPUB/images/cover%s" % cover_ext, f.read(), zipfile.ZIP_DEFLATED))

    # 9) 压缩写出
    report(60, "压缩写入 EPUB ...")
    with zipfile.ZipFile(out_path, "w") as zf:
        for arcname, data, compress in file_specs:
            check_control(pause_event, cancel_event)
            zf.writestr(arcname, data, compress_type=compress)

    # 10) 结构校验
    report(85, "结构校验 ...")
    errors = validate_epub(out_path, page_count, ext_by_path)
    if errors:
        raise RuntimeError("EPUB 结构校验失败：\n" + "\n".join(errors))

    size_mb = os.path.getsize(out_path) / 1024.0 / 1024.0
    report(100, "完成！共 %d 页，%.1f MB" % (page_count, size_mb))
    return out_path


def validate_epub(epub_path, page_count, ext_by_path):
    """EPUB 结构校验：mimetype / container / opf / 页面 / 图片引用 / zip 完整性"""
    errors = []
    try:
        with zipfile.ZipFile(epub_path) as zf:
            names = zf.namelist()
            if "mimetype" not in names or zf.read("mimetype") != b"application/epub+zip":
                errors.append("mimetype 缺失或不正确")
            if "META-INF/container.xml" not in names:
                errors.append("container.xml 缺失")
            if "EPUB/content.opf" not in names:
                errors.append("content.opf 缺失")
            for i in range(1, page_count + 1):
                if "EPUB/page_%03d.xhtml" % i not in names:
                    errors.append("页面 page_%03d.xhtml 缺失" % i)
            img_re = re.compile(r'src="(images/[^"]+)"')
            for i in range(1, page_count + 1):
                try:
                    page_text = zf.read("EPUB/page_%03d.xhtml" % i).decode("utf-8", "replace")
                except KeyError:
                    continue
                for m in img_re.findall(page_text):
                    if "EPUB/" + m not in names:
                        errors.append("page_%03d.xhtml 引用缺失图片 %s" % (i, m))
            bad = zf.testzip()
            if bad:
                errors.append("zip 文件损坏: %s" % bad)
    except zipfile.BadZipFile as e:
        errors.append("不是有效 zip: %s" % e)
    return errors


# ---------------------------------------------------------------- 主转换流程

def convert(input_raw, out_dir, title=None, progress_cb=None, log_cb=None,
            concurrency=DEFAULT_CONCURRENCY, pause_event=None, cancel_event=None):
    """一键转换入口：解析输入 -> 取页面 -> 提取图片 -> 并发下载 -> 生成 EPUB -> 校验。

    取消（DownloadCancelledError）时自动清理临时目录；其余异常同样清理后抛出。
    """
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    os.makedirs(out_dir, exist_ok=True)

    def emit(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)
        if log_cb:
            log_cb("[%3d%%] %s" % (pct, msg))

    # 1) 识别输入
    src_type, url, file_path = resolve_input(input_raw)
    if src_type == "url":
        emit(1, "识别为在线链接，下载页面 HTML ...")
        if "telegra.ph" not in url:
            log_cb and log_cb("[提示] 非 telegra.ph 链接，将尝试按通用网页解析")
        base_name = guess_title_from_url(url)
    else:
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        emit(1, "识别为本地文件：%s" % file_path)

    if not title or not title.strip():
        title = base_name
    title = title.strip()

    # 2) 读取页面
    emit(3, "解析页面 HTML ...")
    html_text = load_html(src_type, url, file_path)
    img_urls = extract_image_urls(html_text)
    if not img_urls:
        raise ValueError("页面中未找到任何漫画图片，请确认输入的是 telegra.ph 漫画网页")
    emit(5, "共提取到 %d 张漫画图片" % len(img_urls))

    # 3) 并发下载图片到临时目录（取消 / 异常时清理）
    tmp_dir = tempfile.mkdtemp(prefix="telegraph_epub_")
    try:
        emit(6, "开始并发下载图片（并发 %d）..." % concurrency)
        img_paths = download_images_concurrently(
            img_urls, tmp_dir, concurrency=concurrency,
            progress_cb=lambda pct, m: emit(pct, m),
            pause_event=pause_event, cancel_event=cancel_event)

        # 4) 生成 EPUB
        out_name = sanitize_filename(title) + ".epub"
        out_path = os.path.join(out_dir, out_name)
        if os.path.exists(out_path):  # 避免覆盖
            n = 1
            while os.path.exists(os.path.join(out_dir, "%s_%d.epub" % (sanitize_filename(title), n))):
                n += 1
            out_path = os.path.join(out_dir, "%s_%d.epub" % (sanitize_filename(title), n))

        emit(65, "生成 EPUB：%s" % os.path.basename(out_path))
        build_epub(img_paths, title, out_path, progress_cb=emit,
                   pause_event=pause_event, cancel_event=cancel_event)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return out_path


# ---------------------------------------------------------------- 批量转换

def scan_dir_for_html(dir_path):
    """扫描文件夹内所有 Telegraph 漫画网页文件。

    匹配规则：扩展名为 .html/.htm，或无扩展名文件；
    文件名含 "telegraph"（telegra.ph 整页保存的默认命名）直接命中；
    否则读取文件头 4KB，内容含 "telegra.ph" 也命中。
    """
    hits = []
    if not os.path.isdir(dir_path):
        raise ValueError("目录不存在：" + dir_path)
    for name in sorted(os.listdir(dir_path)):
        p = os.path.join(dir_path, name)
        if not os.path.isfile(p):
            continue
        low = name.lower()
        is_html = low.endswith((".html", ".htm"))
        is_noext = "." not in low
        if not (is_html or is_noext):
            continue
        if "telegraph" in low:
            hits.append(p)
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(4096)
            if "telegra.ph" in head.lower():
                hits.append(p)
        except Exception:
            pass
    return hits


def convert_batch(inputs, out_dir, title=None, progress_cb=None, log_cb=None,
                  concurrency=DEFAULT_CONCURRENCY, pause_event=None, cancel_event=None):
    """批量转换入口：逐个转换并汇总结果。

    inputs: 输入列表（本地路径 / 在线链接均可）
    title : 仅在单输入时生效；批量时自动取各文件标题
    返回 [(input, ok, detail)]，detail 为输出路径（成功）、错误信息（失败）或"已取消"。
    暂停 / 取消对后续任务同样生效：取消时未开始项直接标记"已取消"。
    """
    total = len(inputs)
    results = []
    line = (lambda m: log_cb(m)) if log_cb else (lambda m: None)

    def finish_summary():
        ok = sum(1 for _, ok_, _ in results if ok_)
        fail = sum(1 for _, ok_, d in results if not ok_ and d != "已取消")
        canc = sum(1 for _, ok_, d in results if d == "已取消")
        line("")
        line("批量转换完成：成功 %d，失败 %d，取消 %d" % (ok, fail, canc))
        return results

    for idx, inp in enumerate(inputs, 1):
        # 任务开始前的暂停 / 取消检查
        try:
            wait_resume(pause_event, cancel_event)
        except DownloadCancelledError:
            for inp2 in inputs[idx - 1:]:
                results.append((inp2, False, "已取消"))
            line("[取消] 用户取消，剩余 %d 项未执行" % (total - idx + 1))
            return finish_summary()

        base = (idx - 1) * 100.0 / total
        span = 100.0 / total

        def make_progress(base=base, span=span):
            def cb(pct, msg):
                if progress_cb:
                    progress_cb(int(base + span * pct), msg)
            return cb

        line("")
        line("[%d/%d] 开始转换：%s" % (idx, total, inp))
        try:
            out_path = convert(inp, out_dir,
                               title=title if total == 1 else None,
                               progress_cb=make_progress(), log_cb=line,
                               concurrency=concurrency,
                               pause_event=pause_event, cancel_event=cancel_event)
            results.append((inp, True, out_path))
            line("[%d/%d] 成功：%s" % (idx, total, out_path))
        except DownloadCancelledError:
            results.append((inp, False, "已取消"))
            line("[%d/%d] 取消：%s" % (idx, total, inp))
            for inp2 in inputs[idx:]:
                results.append((inp2, False, "已取消"))
            line("[取消] 当前及后续任务已取消")
            return finish_summary()
        except Exception as e:
            results.append((inp, False, str(e)))
            line("[%d/%d] 失败：%s" % (idx, total, e))
    return finish_summary()


# ---------------------------------------------------------------- GUI

if TK_AVAILABLE:

    class ConverterApp:
        """简洁 tkinter 交互界面（批量输入 + 并发下载 + 暂停/取消）"""

        def __init__(self, root):
            self.root = root
            self.queue = queue.Queue()
            self.worker = None
            self.pause_event = threading.Event()
            self.pause_event.set()
            self.cancel_event = threading.Event()

            root.title("telegra.ph 漫画 → EPUB 转换器（批量 / 并发）")
            root.geometry("720x660")
            root.minsize(640, 560)

            pad = {"padx": 10, "pady": 5}
            frm = ttk.Frame(root, padding=10)
            frm.pack(fill="both", expand=True)

            # ① 输入列表（多输入）
            ttk.Label(frm, text="① 输入列表（在线链接 / 本地文件 / 文件夹扫描，支持多条）:").grid(
                row=0, column=0, columnspan=4, sticky="w", **pad)
            list_frame = ttk.Frame(frm)
            list_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=2)
            self.input_list = tk.Listbox(list_frame, height=6, selectmode=tk.EXTENDED)
            self.input_list.pack(side="left", fill="both", expand=True)
            list_scroll = ttk.Scrollbar(list_frame, command=self.input_list.yview)
            list_scroll.pack(side="left", fill="y")
            self.input_list.config(yscrollcommand=list_scroll.set)

            btn_frame = ttk.Frame(frm)
            btn_frame.grid(row=2, column=0, columnspan=4, sticky="w", padx=10, pady=4)
            ttk.Button(btn_frame, text="添加文件...", command=self.browse_input).pack(side="left", padx=2)
            ttk.Button(btn_frame, text="添加链接...", command=self.add_link).pack(side="left", padx=2)
            ttk.Button(btn_frame, text="添加文件夹(扫描)...", command=self.browse_dir_input).pack(side="left", padx=2)
            ttk.Button(btn_frame, text="删除选中", command=self.remove_selected).pack(side="left", padx=2)
            ttk.Button(btn_frame, text="清空", command=self.clear_inputs).pack(side="left", padx=2)

            # ② 输出目录
            ttk.Label(frm, text="② 输出目录:").grid(row=3, column=0, columnspan=4, sticky="w", **pad)
            self.out_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
            ttk.Entry(frm, textvariable=self.out_var).grid(
                row=4, column=0, sticky="ew", padx=(10, 5), pady=5)
            ttk.Button(frm, text="浏览...", command=self.browse_out).grid(
                row=4, column=1, columnspan=3, padx=5, pady=5)

            # ③ 书名（可选）
            ttk.Label(frm, text="③ 书名（可选；仅单个输入时生效，批量自动取各文件标题）:").grid(
                row=5, column=0, columnspan=4, sticky="w", **pad)
            self.title_var = tk.StringVar()
            ttk.Entry(frm, textvariable=self.title_var).grid(
                row=6, column=0, columnspan=4, sticky="ew", padx=10, pady=5)

            # 转换按钮 + 并发数 + 暂停/取消
            ctrl_frame = ttk.Frame(frm)
            ctrl_frame.grid(row=7, column=0, columnspan=4, pady=8)
            self.convert_btn = ttk.Button(ctrl_frame, text="开始批量转换", command=self.start_convert)
            self.convert_btn.pack(side="left", padx=4)
            ttk.Label(ctrl_frame, text="并发:").pack(side="left", padx=(14, 2))
            self.jobs_var = tk.IntVar(value=DEFAULT_CONCURRENCY)
            ttk.Spinbox(ctrl_frame, from_=MIN_CONCURRENCY, to=MAX_CONCURRENCY, width=4,
                        textvariable=self.jobs_var).pack(side="left")
            self.pause_btn = ttk.Button(ctrl_frame, text="暂停", command=self.on_pause_toggle,
                                        state="disabled")
            self.pause_btn.pack(side="left", padx=4)
            self.cancel_btn = ttk.Button(ctrl_frame, text="取消", command=self.on_cancel,
                                         state="disabled")
            self.cancel_btn.pack(side="left", padx=4)

            # 进度
            self.progress = ttk.Progressbar(frm, mode="determinate", maximum=100)
            self.progress.grid(row=8, column=0, columnspan=4, sticky="ew", padx=10, pady=5)
            self.status_var = tk.StringVar(value="就绪")
            ttk.Label(frm, textvariable=self.status_var, anchor="w").grid(
                row=9, column=0, columnspan=4, sticky="ew", padx=10, pady=5)

            # 日志
            ttk.Label(frm, text="运行日志:").grid(row=10, column=0, columnspan=4, sticky="w", **pad)
            self.log_text = tk.Text(frm, height=9, state="disabled", wrap="word")
            self.log_text.grid(row=11, column=0, columnspan=3, sticky="nsew", padx=10, pady=5)
            log_scroll = ttk.Scrollbar(frm, command=self.log_text.yview)
            log_scroll.grid(row=11, column=3, sticky="ns", pady=5)
            self.log_text.config(yscrollcommand=log_scroll.set)

            frm.rowconfigure(11, weight=1)
            frm.columnconfigure(0, weight=1)

            self.root.protocol("WM_DELETE_WINDOW", self.on_close)
            self.root.after(100, self.poll_queue)

        # ---- 输入列表操作
        def browse_input(self):
            ps = filedialog.askopenfilenames(title="选择本地 HTML 文件（可多选）",
                                             filetypes=[("网页文件", "*.html *.htm"), ("所有文件", "*.*")])
            for p in ps:
                self.input_list.insert(tk.END, p)

        def add_link(self):
            """弹窗粘贴在线链接（每行一个）"""
            win = tk.Toplevel(self.root)
            win.title("添加在线链接")
            win.geometry("540x240")
            ttk.Label(win, text="粘贴 telegra.ph 链接（每行一个，可添加多个）:").pack(
                anchor="w", padx=10, pady=(10, 5))
            txt = tk.Text(win, height=6)
            txt.pack(fill="both", expand=True, padx=10)

            def ok():
                for line in txt.get("1.0", tk.END).splitlines():
                    line = line.strip()
                    if line:
                        self.input_list.insert(tk.END, line)
                win.destroy()

            def cancel():
                win.destroy()

            btns = ttk.Frame(win)
            btns.pack(pady=8)
            ttk.Button(btns, text="确定", command=ok).pack(side="left", padx=6)
            ttk.Button(btns, text="取消", command=cancel).pack(side="left", padx=6)
            txt.focus_set()

        def browse_dir_input(self):
            """选择文件夹：扫描其中所有 Telegraph 网页文件并加入输入列表"""
            d = filedialog.askdirectory(title="选择包含漫画网页的文件夹")
            if not d:
                return
            try:
                hits = scan_dir_for_html(d)
            except Exception as e:
                messagebox.showerror("错误", str(e))
                return
            if not hits:
                messagebox.showwarning("提示",
                                       "该文件夹下未找到 Telegraph 网页文件\n"
                                       "（.html/.htm 或无扩展名，且文件名含 telegraph 或内容含 telegra.ph）")
                return
            for h in hits:
                self.input_list.insert(tk.END, h)
            messagebox.showinfo("提示", "已添加 %d 个文件到输入列表" % len(hits))

        def remove_selected(self):
            sel = self.input_list.curselection()
            for idx in reversed(sel):
                self.input_list.delete(idx)

        def clear_inputs(self):
            self.input_list.delete(0, tk.END)

        def browse_out(self):
            d = filedialog.askdirectory(title="选择输出目录")
            if d:
                self.out_var.set(d)

        # ---- 控制（暂停/继续、取消）
        def on_pause_toggle(self):
            if self.pause_event.is_set():
                self.pause_event.clear()
                self.pause_btn.config(text="继续")
                self.append_log("[暂停] 已暂停，下载与打包将等待，点击「继续」恢复")
            else:
                self.pause_event.set()
                self.pause_btn.config(text="暂停")
                self.append_log("[继续] 已继续")

        def on_cancel(self):
            self.cancel_event.set()
            self.cancel_btn.config(state="disabled")
            self.status_var.set("正在取消...")
            self.append_log("[取消] 用户请求取消，正在停止下载与后续任务...")

        # ---- 日志与进度
        def append_log(self, msg):
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")

        def poll_queue(self):
            try:
                while True:
                    kind, payload = self.queue.get_nowait()
                    if kind == "progress":
                        pct, msg = payload
                        self.progress["value"] = pct
                        self.status_var.set(msg)
                    elif kind == "log":
                        self.append_log(payload)
                    elif kind == "batch_done":
                        results, out_dir = payload
                        ok = [r for r in results if r[1]]
                        fail = [r for r in results if not r[1] and r[2] != "已取消"]
                        canc = [r for r in results if r[2] == "已取消"]
                        self.convert_btn.config(state="normal")
                        self.pause_btn.config(state="disabled", text="暂停")
                        self.cancel_btn.config(state="disabled")
                        self.pause_event.set()
                        self.status_var.set("批量转换完成：成功 %d，失败 %d，取消 %d"
                                            % (len(ok), len(fail), len(canc)))
                        if fail:
                            msg = "成功 %d / 失败 %d / 取消 %d：\n" % (len(ok), len(fail), len(canc))
                            for inp, _, err in fail:
                                msg += "\n✗ %s\n   原因: %s" % (inp, err)
                            messagebox.showwarning("批量转换完成（部分失败）", msg)
                        if ok:
                            if len(ok) == 1 and len(results) == 1:
                                if messagebox.askyesno("转换完成",
                                                       "EPUB 已生成：\n%s\n\n是否立即打开文件？" % ok[0][2]):
                                    self.open_file(ok[0][2])
                            else:
                                if messagebox.askyesno(
                                        "转换完成",
                                        "成功生成 %d 个 EPUB（输出目录：\n%s）\n\n是否打开输出目录？"
                                        % (len(ok), out_dir)):
                                    self.open_dir(out_dir)
                    elif kind == "error":
                        err = payload
                        self.convert_btn.config(state="normal")
                        self.pause_btn.config(state="disabled", text="暂停")
                        self.cancel_btn.config(state="disabled")
                        self.pause_event.set()
                        self.status_var.set("转换失败")
                        messagebox.showerror("转换失败", str(err))
            except queue.Empty:
                pass
            self.root.after(100, self.poll_queue)

        @staticmethod
        def open_file(path):
            try:
                if sys.platform.startswith("win"):
                    os.startfile(path)  # noqa
                elif sys.platform == "darwin":
                    import subprocess
                    subprocess.Popen(["open", path])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                messagebox.showwarning("提示", "无法自动打开文件：%s" % e)

        @staticmethod
        def open_dir(path):
            try:
                if sys.platform.startswith("win"):
                    os.startfile(path)  # noqa
                elif sys.platform == "darwin":
                    import subprocess
                    subprocess.Popen(["open", path])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                messagebox.showwarning("提示", "无法自动打开目录：%s" % e)

        # ---- 转换
        def start_convert(self):
            if self.worker and self.worker.is_alive():
                messagebox.showinfo("提示", "正在转换中，请稍候")
                return
            inputs = [s.strip() for s in self.input_list.get(0, tk.END) if s.strip()]
            out_dir = self.out_var.get().strip() or os.path.join(os.path.expanduser("~"), "Downloads")
            title = self.title_var.get().strip()
            if not inputs:
                messagebox.showwarning("提示", "请先添加至少一个输入（链接 / 文件 / 文件夹扫描）")
                return
            try:
                jobs = max(MIN_CONCURRENCY, min(MAX_CONCURRENCY, int(self.jobs_var.get())))
            except (TypeError, ValueError):
                jobs = DEFAULT_CONCURRENCY
            self.pause_event = threading.Event()
            self.pause_event.set()
            self.cancel_event = threading.Event()
            self.convert_btn.config(state="disabled")
            self.pause_btn.config(state="normal", text="暂停")
            self.cancel_btn.config(state="normal")
            self.progress["value"] = 0
            self.status_var.set("开始 ...")
            self.append_log("== 开始批量转换 ==")
            self.append_log("输入 %d 项:" % len(inputs))
            for i, s in enumerate(inputs, 1):
                self.append_log("  %d. %s" % (i, s))
            self.append_log("输出目录: %s" % out_dir)
            self.append_log("并发下载: %d 线程" % jobs)
            if len(inputs) > 1 and title:
                self.append_log("[提示] 批量模式自动取各文件标题，书名栏仅对单输入生效")
            self.worker = threading.Thread(
                target=self._run, args=(inputs, out_dir, title, jobs), daemon=True)
            self.worker.start()

        def _run(self, inputs, out_dir, title, jobs):
            def cb(pct, msg):
                self.queue.put(("progress", (pct, msg)))

            def log_only(msg):
                self.queue.put(("log", msg))

            try:
                results = convert_batch(inputs, out_dir, title=title,
                                        progress_cb=cb, log_cb=log_only,
                                        concurrency=jobs,
                                        pause_event=self.pause_event,
                                        cancel_event=self.cancel_event)
                self.queue.put(("batch_done", (results, out_dir)))
            except Exception as e:
                self.queue.put(("error", e))

        def on_close(self):
            self.root.destroy()


# ---------------------------------------------------------------- 主入口

def run_cli(argv):
    """命令行模式（支持批量 / 并发 / 暂停 / 取消）：

      单输入  : --cli <链接或路径> [--out 目录] [--title 书名] [--jobs 1-64]
      多输入  : --cli <输入1> <输入2> ... [--out 目录]
      扫文件夹: --cli --dir <文件夹> [--out 目录]
      组合    : --cli <输入1> --dir <文件夹> ... [--out 目录]

    转换中控制信号（Windows）：
      Ctrl+C    → 优雅取消（清理临时文件，已完成保留、未完成标记取消）
      Ctrl+Break→ 暂停 / 继续切换
    """
    args = list(argv)

    def take(flag):
        nonlocal args
        if flag in args:
            i = args.index(flag)
            args.pop(i)
            return args.pop(i)
        return None

    dirs = []
    while True:
        d = take("--dir")
        if d is None:
            break
        dirs.append(d)
    out_dir = take("--out") or os.path.join(os.path.expanduser("~"), "Downloads")
    title = take("--title")
    jobs_str = take("--jobs")
    concurrency = DEFAULT_CONCURRENCY
    if jobs_str:
        try:
            concurrency = max(MIN_CONCURRENCY, min(MAX_CONCURRENCY, int(jobs_str)))
        except ValueError:
            log("[提示] --jobs 参数无效，使用默认 %d" % DEFAULT_CONCURRENCY)

    inputs = [a for a in args if a.strip() and not a.startswith("--")]
    for d in dirs:
        inputs.extend(scan_dir_for_html(d))

    if not inputs:
        log("用法:")
        log("  单输入  : python telegraph-epub-converter.py --cli <链接或路径> [--out 目录] [--title 书名] [--jobs 1-64]")
        log("  多输入  : python telegraph-epub-converter.py --cli <输入1> <输入2> ... [--out 目录]")
        log("  扫文件夹: python telegraph-epub-converter.py --cli --dir <文件夹> [--out 目录]")
        log("  组合    : python telegraph-epub-converter.py --cli <输入1> --dir <文件夹> ... [--out 目录]")
        log("转换中：Ctrl+C 取消，Ctrl+Break 暂停/继续")
        return 1

    # 控制事件与信号
    pause_event = threading.Event()
    pause_event.set()
    cancel_event = threading.Event()

    def toggle_pause(signum=None, frame=None):
        if pause_event.is_set():
            pause_event.clear()
            log("[暂停] 已暂停（下载/打包等待中），按 Ctrl+Break 继续")
        else:
            pause_event.set()
            log("[继续] 已继续")

    def do_cancel(signum=None, frame=None):
        cancel_event.set()
        log("[取消] 收到取消信号，正在优雅停止...")

    try:
        signal.signal(signal.SIGINT, do_cancel)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, toggle_pause)
        except Exception:
            pass
    else:
        try:
            signal.signal(signal.SIGTSTP, toggle_pause)
        except Exception:
            pass

    log("输入 %d 项:" % len(inputs))
    for i, inp in enumerate(inputs, 1):
        log("  %d. %s" % (i, inp))
    log("输出目录: %s" % out_dir)
    log("并发下载: %d 线程（Ctrl+C 取消，Ctrl+Break 暂停/继续）" % concurrency)
    if len(inputs) > 1 and title:
        log("[提示] 批量模式自动取各文件标题，--title 仅对单输入生效")

    results = convert_batch(inputs, out_dir, title=title, log_cb=log,
                            concurrency=concurrency,
                            pause_event=pause_event, cancel_event=cancel_event)
    ok = sum(1 for _, ok_, _ in results if ok_)
    failed = [(i, d) for i, ok_, d in results if not ok_ and d != "已取消"]
    cancelled = [(i, d) for i, ok_, d in results if d == "已取消"]
    log("")
    if cancelled:
        log("用户取消：成功 %d，失败 %d，取消 %d" % (ok, len(failed), len(cancelled)))
        return 130
    if failed:
        log("以下 %d 项转换失败：" % len(failed))
        for i, err in failed:
            log("  - %s" % i)
            log("    原因: %s" % err)
        return 2
    log("全部转换成功：共 %d 项" % ok)
    return 0


def main():
    if "--cli" in sys.argv:
        sys.exit(run_cli(sys.argv[sys.argv.index("--cli") + 1:]))
    if not TK_AVAILABLE:
        log("当前环境无图形界面，请使用命令行模式：")
        log("python telegraph-epub-converter.py --cli <链接或路径> [--out 目录] [--title 书名] [--jobs 1-64]")
        log("或批量模式：--cli 输入1 输入2 ... / --cli --dir 文件夹")
        log("转换中：Ctrl+C 取消，Ctrl+Break 暂停/继续")
        return 1
    root = tk.Tk()
    ConverterApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
