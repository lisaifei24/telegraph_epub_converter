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
  9. 版本管理：
     - GUI 窗口标题显示当前版本号，并提供「检查更新」按钮（启动时也会静默检查一次）
     - CLI 支持 `--version` 输出版本号
     - 通过 GitHub API 查询最新 Release，若远程版本高于本地则弹窗提示下载链接
       （仅提示，不自动下载；网络失败时静默忽略，不影响使用）
  10. EPUB 元数据编辑：支持设置标题 / 作者 / 语言 / 标签 / 描述并写入 OPF 元数据
      （GUI 输入框，CLI 用 --author / --language / --tags / --description）
  11. 章节分组：支持按卷 / 话分组生成嵌套目录（EPUB3 nav 多级 + NCX 兼容）；
      GUI 输入如「第1卷:1-20,第2卷:21-40」，CLI 用 --chapters 参数
  12. 封面自定义：GUI 可选择本地图片作为封面，CLI 用 --cover 参数；未选择时保持自动封面
  13. CSS 排版注入：可定制页面背景 / 图片边距等样式（GUI 预设 + 自定义文本，CLI 用 --css / --css-file）

用法：
  * 双击脚本 → 弹出 GUI，通过"添加文件 / 添加链接 / 添加文件夹"建立输入列表后批量转换；
    转换中可用"暂停/继续"与"取消"按钮控制
  * 命令行（无界面）：
      单输入  : python telegraph-epub-converter.py --cli <本地路径或在线链接> [--out <输出目录>] [--title <书名>] [--jobs <1-64>]
      多输入  : python telegraph-epub-converter.py --cli <输入1> <输入2> ... [--out <输出目录>]
      扫文件夹: python telegraph-epub-converter.py --cli --dir <文件夹> [--out <输出目录>]
      组合    : python telegraph-epub-converter.py --cli <输入1> --dir <文件夹> ... [--out <输出目录>]
      查版本  : python telegraph-epub-converter.py --version
    可选参数：
      --author <作者>   --language <语言，默认 zh>   --tags <标签A,标签B>
      --description <描述>
      --chapters <分组>，如 "第1卷:1-20,第2卷:21-40"（生成多级目录）
      --cover <本地图片路径>（自定义封面；缺省用首页图片自动生成封面）
      --css <CSS文本> 或 --css-file <CSS文件路径>（自定义页面排版样式）
    转换中：Ctrl+C 取消，Ctrl+Break 暂停/继续（Windows）
"""

import os
import re
import sys
import time
import json
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
VERSION = "1.3.0"   # 当前版本号（v1.3.0：新增 EPUB 元数据编辑、章节分组、封面自定义、CSS 排版注入）
GITHUB_REPO = "lisaifei24/telegraph_epub_converter"      # 用于更新检查的 GitHub 仓库
RELEASE_BASE_URL = "https://github.com/%s/releases/download" % GITHUB_REPO
CHECK_UPDATE_TIMEOUT = 8                                 # 更新检查网络超时（秒），失败静默
IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
DEFAULT_CONCURRENCY = 16      # 默认并发下载线程数
MAX_CONCURRENCY = 64         # 并发数上限
MIN_CONCURRENCY = 1

# ---- v1.3.0 CSS 排版注入 ----
DEFAULT_CSS = (
    "body{margin:0;padding:0;text-align:center;background:#000;}\n"
    "img{width:100%;max-width:100%;height:auto;display:block;margin:0 auto;}"
)
CSS_PRESETS = {
    "深色（默认）": DEFAULT_CSS,
    "浅色": "body{margin:0;padding:0;text-align:center;background:#fff;}\n"
            "img{width:100%;max-width:100%;height:auto;display:block;margin:0 auto;}",
    "浅色留白": "body{margin:0;padding:12px;text-align:center;background:#fff;}\n"
              "img{width:100%;max-width:100%;height:auto;display:block;margin:0 auto;}",
}


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

def _parse_version(v):
    """从 'v1.2.0' / '1.2.0' 解析出 (major, minor, patch) 元组；解析失败返回 None。"""
    s = str(v or "").strip().lstrip("vV")
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", s)
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def check_latest_release(timeout=CHECK_UPDATE_TIMEOUT):
    """查询 GitHub 最新 Release（8 秒超时）。

    返回 (latest_tag, download_url)：latest_tag 形如 'v1.2.0'，download_url 为对应
    exe 下载链接；网络失败 / 无 Release / 解析异常时返回 None（调用方静默忽略）。
    仅查询与提示，不自动下载。
    """
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO,
            headers={"User-Agent": UA["User-Agent"], "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = (data or {}).get("tag_name", "") if isinstance(data, dict) else ""
        if not tag:
            return None
        url = "%s/%s/telegraph_epub_converter.exe" % (RELEASE_BASE_URL, tag)
        return tag, url
    except Exception:
        return None


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
    """按出现顺序提取 HTML 中的漫画图片引用。

    支持两种来源：
    - http(s) 外链（telegra.ph 原图 / 图床）
    - 本地相对路径（浏览器整页保存时，如 ./xxx_files/0001.webp）
    """
    urls = re.findall(r'<img[^>]*src=["\']([^"\']+)["\']', html_text, re.I)
    seen, out = set(), []
    for u in urls:
        u = html_mod.unescape(u)
        if u in seen:
            continue
        seen.add(u)
        low = u.lstrip().lower()
        if low.startswith("data:"):
            continue
        if re.search(r"\.(jpe?g|png|gif|webp|avif|bmp|svg)(\?|#.*)?$", low) or "telegra.ph" in low:
            out.append(u)
    return out


def resolve_local_image_ref(u, html_path):
    """把本地 HTML 中提取的图片引用解析为绝对路径；网络 URL 原样返回。"""
    if u.lower().startswith(("http://", "https://", "data:")):
        return u
    base = os.path.dirname(os.path.abspath(html_path))
    return os.path.normpath(os.path.join(base, u))


def download_image(url, dest):
    """下载单张图片到本地，返回字节数（支持网络 URL 与本地路径）"""
    if url.lower().startswith(("http://", "https://")):
        data = fetch(url)
    else:
        with open(url, "rb") as f:
            data = f.read()
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


def build_page_xhtml(title, page_no, img_src, css=None):
    """生成单页 XHTML，可注入自定义 CSS（v1.3.0）"""
    style = css if css is not None else DEFAULT_CSS
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>第 %d 页</title>\n'
        '<style>%s</style>\n'
        '</head>\n'
        '<body><div><img src="%s" alt="page %d"/></div></body>\n'
        '</html>\n' % (page_no, style, img_src, page_no)
    )


def parse_chapters(spec, page_count):
    """解析章节分组描述（v1.3.0）。

    格式：分组名:页码范围 以 , 或 ; 分隔，如 "第1卷:1-20,第2卷:21-40"
    页码范围支持 "1-20"、"21"（单页）。返回 [(label, start, end), ...]；
    未提供分组返回 None；格式非法或范围越界抛出 ValueError（信息含原因）。
    """
    if spec is None:
        return None
    spec = (spec or "").strip()
    if not spec:
        return None
    groups = []
    for part in re.split(r"[,;，；]", spec):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.+?)\s*[:：]\s*(\d+)(?:\s*-\s*(\d+))?$", part)
        if not m:
            raise ValueError("章节分组格式错误：%r（应为 分组名:页码范围，如 第1卷:1-20）" % part)
        label = m.group(1).strip()
        start = int(m.group(2))
        end = int(m.group(3)) if m.group(3) else start
        if start < 1 or end < start or end > page_count:
            raise ValueError(
                "章节分组越界：%r（页码范围 %d-%d，本书共 %d 页）" % (label, start, end, page_count))
        groups.append((label, start, end))
    if not groups:
        raise ValueError("章节分组描述为空，请检查 --chapters 参数")
    return groups


def build_nav_entries(title, page_count, chapters=None):
    """构建 EPUB3 nav.xhtml 的 <ol> 目录条目；chapters 非空时生成多级嵌套"""
    if not chapters:
        return "".join(
            '<li><a href="page_%03d.xhtml">第 %d 页</a></li>' % (i, i)
            for i in range(1, page_count + 1)
        )
    parts = []
    for label, start, end in chapters:
        pages = "".join(
            '<li><a href="page_%03d.xhtml">第 %d 页</a></li>' % (i, i)
            for i in range(start, end + 1)
        )
        parts.append('<li><span>%s</span>\n<ol>\n%s\n</ol>\n</li>'
                     % (html_escape(label), pages))
    return "\n".join(parts)


def build_ncx(title, epub_id, page_count, chapters=None):
    """生成 EPUB2 兼容 toc.ncx；chapters 非空时生成嵌套 navPoint"""
    if not chapters:
        nav_points = "".join(
            '<navPoint id="p%d" playOrder="%d"><navLabel><text>第 %d 页</text></navLabel>'
            '<content src="page_%03d.xhtml"/></navPoint>' % (i, i, i, i)
            for i in range(1, page_count + 1)
        )
    else:
        order = 0
        nav_points = []
        for gidx, (label, start, end) in enumerate(chapters, 1):
            order += 1
            group_id = "g%d" % gidx
            children = []
            for i in range(start, end + 1):
                order += 1
                children.append(
                    '<navPoint id="p%d" playOrder="%d"><navLabel><text>第 %d 页</text></navLabel>'
                    '<content src="page_%03d.xhtml"/></navPoint>' % (i, order, i, i))
            nav_points.append(
                '<navPoint id="%s" playOrder="%d"><navLabel><text>%s</text></navLabel>\n'
                '%s\n</navPoint>' % (group_id, order - (end - start + 1), html_escape(label),
                                     "\n".join(children)))
        nav_points = "\n".join(nav_points)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        '  <head><meta name="dtb:uid" content="%s"/></head>\n'
        '  <docTitle><text>%s</text></docTitle>\n'
        '  <navMap>\n%s\n  </navMap>\n'
        '</ncx>\n' % (html_escape(epub_id), html_escape(title), nav_points)
    )


def build_epub(images, title, out_path, progress_cb=None, pause_event=None, cancel_event=None,
               author=None, language=None, tags=None, description=None,
               chapters=None, cover_path=None, css=None):
    """手写 EPUB3（含 NCX 兼容老阅读器），逐页排版漫画图片。

    images: 本地图片绝对路径列表（已按页面顺序）
    title : 书名
    out_path: 输出 .epub 路径
    v1.3.0 新增：
      author      - 作者（写入 OPF dc:creator）
      language    - 语言（默认 zh，写入 OPF dc:language）
      tags        - 标签列表（每个写入 OPF dc:subject）
      description - 描述（写入 OPF dc:description）
      chapters    - 章节分组 [(label, start, end), ...]，生成多级目录
      cover_path  - 自定义封面本地图片路径；缺省用首页图片自动生成封面
      css         - 自定义页面排版 CSS（控制页面背景 / 图片边距等），缺省深色
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
    if cover_path:
        cover_ext = os.path.splitext(cover_path)[1].lower() or ".jpg"
        if cover_ext not in IMG_EXTS:
            cover_ext = ".jpg"
        if cover_ext == ".jpeg":
            cover_ext = ".jpg"
        cover_arcname = "images/cover%s" % cover_ext
        cover_img_name = "cover%s" % cover_ext
    else:
        cover_ext = ext_by_path[0]
        cover_arcname = "images/cover%s" % cover_ext
        cover_img_name = "cover%s" % cover_ext
    style = css if css is not None else DEFAULT_CSS
    lang = (language or "zh").strip() or "zh"

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
        xhtml = build_page_xhtml(title, i, "images/page_%03d%s" % (i, ext), css=style)
        file_specs.append(("EPUB/page_%03d.xhtml" % i, xhtml.encode("utf-8"), zipfile.ZIP_DEFLATED))

    # 4) 封面 XHTML（默认首页图片；v1.3.0 支持自定义封面）
    check_control(pause_event, cancel_event)
    cover_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>封面</title>\n'
        '<style>%s</style>\n'
        '</head>\n'
        '<body><div><img src="%s" alt="cover"/></div></body>\n'
        '</html>\n' % (style, cover_arcname)
    )
    file_specs.append(("EPUB/cover.xhtml", cover_xhtml.encode("utf-8"), zipfile.ZIP_DEFLATED))

    # 5) nav.xhtml（EPUB3 目录导航；v1.3.0 支持多级嵌套）
    check_control(pause_event, cancel_event)
    nav_entries = build_nav_entries(title, page_count, chapters)
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

    # 6) toc.ncx（EPUB2 兼容；v1.3.0 支持嵌套 navPoint）
    check_control(pause_event, cancel_event)
    file_specs.append(("EPUB/toc.ncx",
                       build_ncx(title, epub_id, page_count, chapters).encode("utf-8"),
                       zipfile.ZIP_DEFLATED))

    # 7) content.opf（清单 + 书脊；v1.3.0 支持自定义元数据）
    check_control(pause_event, cancel_event)
    manifest_items = []
    manifest_items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    manifest_items.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    manifest_items.append('<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
    for i in range(1, page_count + 1):
        manifest_items.append('<item id="page_%03d" href="page_%03d.xhtml" media-type="application/xhtml+xml"/>'
                              % (i, i))
    cover_img_props = ' properties="cover-image"' if cover_path else ""
    manifest_items.append('<item id="cover_img" href="images/cover%s" media-type="%s"%s/>'
                          % (cover_ext, media_type(cover_ext), cover_img_props))
    for i, ext in enumerate(ext_by_path, 1):
        manifest_items.append('<item id="img_%03d" href="images/page_%03d%s" media-type="%s"/>'
                              % (i, i, ext, media_type(ext)))

    spine_items = ['<itemref idref="cover"/>'] + \
                  ['<itemref idref="page_%03d"/>' % i for i in range(1, page_count + 1)]

    meta_extra = []
    if author:
        meta_extra.append('    <dc:creator>%s</dc:creator>' % html_escape(author))
    for tag in (tags or []):
        tag = (tag or "").strip()
        if tag:
            meta_extra.append('    <dc:subject>%s</dc:subject>' % html_escape(tag))
    if description:
        meta_extra.append('    <dc:description>%s</dc:description>' % html_escape(description))
    meta_block = "\n".join(meta_extra)

    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang="%s">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">%s</dc:identifier>\n'
        '    <dc:title>%s</dc:title>\n'
        '    <dc:language>%s</dc:language>\n'
        '    <dc:date>%s</dc:date>\n'
        '%s\n'
        '    <meta property="dcterms:modified">%sT00:00:00Z</meta>\n'
        '  </metadata>\n'
        '  <manifest>\n%s\n  </manifest>\n'
        '  <spine toc="ncx">\n%s\n  </spine>\n'
        '  <guide>\n    <reference type="cover" title="封面" href="cover.xhtml"/>\n  </guide>\n'
        '</package>\n' % (
            html_escape(lang), html_escape(epub_id), html_escape(title), html_escape(lang),
            date_str,
            meta_block if meta_block else "",
            date_str,
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
    if cover_path:
        with open(cover_path, "rb") as f:
            file_specs.append(("EPUB/" + cover_arcname, f.read(), zipfile.ZIP_DEFLATED))
    else:
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
            concurrency=DEFAULT_CONCURRENCY, pause_event=None, cancel_event=None,
            author=None, language=None, tags=None, description=None,
            chapters=None, cover=None, css=None):
    """一键转换入口：解析输入 -> 取页面 -> 提取图片 -> 并发下载 -> 生成 EPUB -> 校验。

    v1.3.0 新增参数：author / language / tags（字符串"a,b"或列表）/ description /
    chapters（"第1卷:1-20,..."）/ cover（本地图片路径）/ css（自定义 CSS 文本）。
    取消（DownloadCancelledError）时自动清理临时目录；其余异常同样清理后抛出。
    """
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    os.makedirs(out_dir, exist_ok=True)

    # 预处理 v1.3.0 选项
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if cover and not os.path.isfile(cover):
        raise ValueError("自定义封面文件不存在：%s" % cover)
    if css is not None:
        css = css.strip() or None
    style = css if css is not None else DEFAULT_CSS

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
    if src_type == "file":
        img_urls = [resolve_local_image_ref(u, file_path) for u in img_urls]
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

        # 4) 生成 EPUB（v1.3.0：元数据 / 章节分组 / 自定义封面 / CSS 注入）
        out_name = sanitize_filename(title) + ".epub"
        out_path = os.path.join(out_dir, out_name)
        if os.path.exists(out_path):  # 避免覆盖
            n = 1
            while os.path.exists(os.path.join(out_dir, "%s_%d.epub" % (sanitize_filename(title), n))):
                n += 1
            out_path = os.path.join(out_dir, "%s_%d.epub" % (sanitize_filename(title), n))

        groups = parse_chapters(chapters, len(img_paths))
        if groups:
            emit(64, "章节分组：%d 组（多级目录）" % len(groups))
        if author:
            emit(64, "作者：%s" % author)
        if tags:
            emit(64, "标签：%s" % ", ".join(tags))
        if description:
            emit(64, "描述：%s" % description[:40] + ("..." if len(description) > 40 else ""))
        if cover:
            emit(64, "自定义封面：%s" % cover)

        emit(65, "生成 EPUB：%s" % os.path.basename(out_path))
        build_epub(img_paths, title, out_path, progress_cb=emit,
                   pause_event=pause_event, cancel_event=cancel_event,
                   author=author, language=language, tags=tags, description=description,
                   chapters=groups, cover_path=cover, css=style)
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
                  concurrency=DEFAULT_CONCURRENCY, pause_event=None, cancel_event=None,
                  author=None, language=None, tags=None, description=None,
                  chapters=None, cover=None, css=None):
    """批量转换入口：逐个转换并汇总结果。

    inputs: 输入列表（本地路径 / 在线链接均可）
    title : 仅在单输入时生效；批量时自动取各文件标题
    v1.3.0 新增 author / language / tags / description / chapters / cover / css，
    与 convert() 同名参数含义一致，透传给每个转换项。
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
                               pause_event=pause_event, cancel_event=cancel_event,
                               author=author, language=language, tags=tags,
                               description=description, chapters=chapters,
                               cover=cover, css=css)
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

            root.title("telegra.ph 漫画 → EPUB 转换器（批量 / 并发） v%s" % VERSION)
            root.geometry("760x880")
            root.minsize(680, 700)

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

            # ④ EPUB 选项（v1.3.0：元数据 / 章节分组 / 封面 / CSS）
            ttk.Label(frm, text="④ EPUB 选项（可选，均可不填）:").grid(
                row=7, column=0, columnspan=4, sticky="w", **pad)

            ttk.Label(frm, text="作者:").grid(row=8, column=0, sticky="e", padx=(10, 2), pady=3)
            self.author_var = tk.StringVar()
            ttk.Entry(frm, textvariable=self.author_var).grid(
                row=8, column=1, sticky="ew", padx=(2, 10), pady=3)
            ttk.Label(frm, text="语言:").grid(row=8, column=2, sticky="e", padx=(10, 2), pady=3)
            self.language_var = tk.StringVar(value="zh")
            ttk.Entry(frm, textvariable=self.language_var, width=10).grid(
                row=8, column=3, sticky="w", padx=(2, 10), pady=3)

            ttk.Label(frm, text="标签:").grid(row=9, column=0, sticky="e", padx=(10, 2), pady=3)
            self.tags_var = tk.StringVar()
            ttk.Entry(frm, textvariable=self.tags_var).grid(
                row=9, column=1, columnspan=3, sticky="ew", padx=(2, 10), pady=3)

            ttk.Label(frm, text="描述:").grid(row=10, column=0, sticky="e", padx=(10, 2), pady=3)
            self.desc_var = tk.StringVar()
            ttk.Entry(frm, textvariable=self.desc_var).grid(
                row=10, column=1, columnspan=3, sticky="ew", padx=(2, 10), pady=3)

            ttk.Label(frm, text="章节分组:").grid(row=11, column=0, sticky="e", padx=(10, 2), pady=3)
            self.chapters_var = tk.StringVar()
            ttk.Entry(frm, textvariable=self.chapters_var).grid(
                row=11, column=1, columnspan=3, sticky="ew", padx=(2, 10), pady=3)
            ttk.Label(frm, text="按卷/话分组生成多级目录，如：第1卷:1-20,第2卷:21-40",
                      foreground="#666666").grid(row=12, column=1, columnspan=3, sticky="w",
                                                 padx=(2, 10), pady=(0, 3))

            ttk.Label(frm, text="封面:").grid(row=13, column=0, sticky="e", padx=(10, 2), pady=3)
            self.cover_var = tk.StringVar()
            ttk.Button(frm, text="选择封面图片...", command=self.browse_cover).grid(
                row=13, column=1, sticky="w", padx=(2, 5), pady=3)
            ttk.Label(frm, textvariable=self.cover_var, foreground="#666666").grid(
                row=13, column=2, columnspan=2, sticky="w", padx=(2, 10), pady=3)

            ttk.Label(frm, text="CSS样式:").grid(row=14, column=0, sticky="e", padx=(10, 2), pady=3)
            self.css_preset_var = tk.StringVar(value="深色（默认）")
            self.css_preset = ttk.Combobox(
                frm, textvariable=self.css_preset_var, state="readonly", width=14,
                values=list(CSS_PRESETS.keys()) + ["自定义"])
            self.css_preset.grid(row=14, column=1, sticky="w", padx=(2, 10), pady=3)
            self.css_preset.bind("<<ComboboxSelected>>", self.on_css_preset)
            self.css_text = tk.Text(frm, height=3, wrap="word")
            self.css_text.grid(row=15, column=1, columnspan=3, sticky="ew", padx=(2, 10), pady=3)
            self.css_text.insert("1.0", DEFAULT_CSS)
            ttk.Label(frm, text="预设即填充到右侧文本框，可继续修改（控制页面背景/图片边距等）",
                      foreground="#666666").grid(row=16, column=1, columnspan=3, sticky="w",
                                                 padx=(2, 10), pady=(0, 3))

            # 转换按钮 + 并发数 + 暂停/取消
            ctrl_frame = ttk.Frame(frm)
            ctrl_frame.grid(row=17, column=0, columnspan=4, pady=8)
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
            ttk.Button(ctrl_frame, text="检查更新", command=self.check_update_manual).pack(side="left", padx=4)

            # 进度
            self.progress = ttk.Progressbar(frm, mode="determinate", maximum=100)
            self.progress.grid(row=18, column=0, columnspan=4, sticky="ew", padx=10, pady=5)
            self.status_var = tk.StringVar(value="就绪")
            ttk.Label(frm, textvariable=self.status_var, anchor="w").grid(
                row=19, column=0, columnspan=3, sticky="ew", padx=(10, 5), pady=5)
            ttk.Label(frm, text="v%s" % VERSION, foreground="#888888").grid(
                row=19, column=3, sticky="e", padx=(0, 10), pady=5)

            # 日志
            ttk.Label(frm, text="运行日志:").grid(row=20, column=0, columnspan=4, sticky="w", **pad)
            self.log_text = tk.Text(frm, height=7, state="disabled", wrap="word")
            self.log_text.grid(row=21, column=0, columnspan=3, sticky="nsew", padx=10, pady=5)
            log_scroll = ttk.Scrollbar(frm, command=self.log_text.yview)
            log_scroll.grid(row=21, column=3, sticky="ns", pady=5)
            self.log_text.config(yscrollcommand=log_scroll.set)

            frm.rowconfigure(21, weight=1)
            frm.columnconfigure(0, weight=1)

            self.root.protocol("WM_DELETE_WINDOW", self.on_close)
            self.root.after(100, self.poll_queue)
            self.root.after(1500, self._auto_check_update)

        # ---- 版本与更新检查
        def _check_update_worker(self, manual):
            result = check_latest_release()
            self.queue.put(("update_result", (manual, result)))

        def check_update_manual(self):
            if self.worker and self.worker.is_alive():
                messagebox.showinfo("提示", "正在转换中，请稍后再检查更新")
                return
            self.append_log("[更新] 正在检查 GitHub 最新版本...")
            threading.Thread(target=self._check_update_worker, args=(True,), daemon=True).start()

        def _auto_check_update(self):
            """启动后静默检查一次：仅在有新版本时提示，网络失败无任何打扰"""
            threading.Thread(target=self._check_update_worker, args=(False,), daemon=True).start()

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

        def browse_cover(self):
            """选择自定义封面图片（v1.3.0）"""
            p = filedialog.askopenfilename(
                title="选择封面图片（jpg / png / gif / webp）",
                filetypes=[("图片文件", "*.jpg *.jpeg *.png *.gif *.webp"), ("所有文件", "*.*")])
            if p:
                self.cover_var.set(p)

        def on_css_preset(self, _event=None):
            """CSS 预设下拉选择后填充到文本框（v1.3.0）"""
            name = self.css_preset_var.get()
            if name in CSS_PRESETS:
                self.css_text.delete("1.0", tk.END)
                self.css_text.insert("1.0", CSS_PRESETS[name])

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

            # ④ EPUB 选项收集（v1.3.0）
            opts = {}
            if self.author_var.get().strip():
                opts["author"] = self.author_var.get().strip()
            lang = self.language_var.get().strip()
            if lang:
                opts["language"] = lang
            if self.tags_var.get().strip():
                opts["tags"] = self.tags_var.get().strip()
            if self.desc_var.get().strip():
                opts["description"] = self.desc_var.get().strip()
            if self.chapters_var.get().strip():
                opts["chapters"] = self.chapters_var.get().strip()
            if self.cover_var.get().strip():
                opts["cover"] = self.cover_var.get().strip()
            css = self.css_text.get("1.0", tk.END).strip()
            if css:
                opts["css"] = css

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
            if opts.get("author"):
                self.append_log("作者: %s" % opts["author"])
            if opts.get("language"):
                self.append_log("语言: %s" % opts["language"])
            if opts.get("tags"):
                self.append_log("标签: %s" % opts["tags"])
            if opts.get("description"):
                self.append_log("描述: %s" % opts["description"])
            if opts.get("chapters"):
                self.append_log("章节分组: %s" % opts["chapters"])
            if opts.get("cover"):
                self.append_log("自定义封面: %s" % opts["cover"])
            if opts.get("css"):
                self.append_log("自定义 CSS: %d 字符" % len(opts["css"]))
            if len(inputs) > 1 and title:
                self.append_log("[提示] 批量模式自动取各文件标题，书名栏仅对单输入生效")
            self.worker = threading.Thread(
                target=self._run, args=(inputs, out_dir, title, jobs, opts), daemon=True)
            self.worker.start()

        def _run(self, inputs, out_dir, title, jobs, opts=None):
            def cb(pct, msg):
                self.queue.put(("progress", (pct, msg)))

            def log_only(msg):
                self.queue.put(("log", msg))

            try:
                results = convert_batch(inputs, out_dir, title=title,
                                        progress_cb=cb, log_cb=log_only,
                                        concurrency=jobs,
                                        pause_event=self.pause_event,
                                        cancel_event=self.cancel_event,
                                        **(opts or {}))
                self.queue.put(("batch_done", (results, out_dir)))
            except Exception as e:
                self.queue.put(("error", e))

        def on_close(self):
            self.root.destroy()


# ---------------------------------------------------------------- 主入口

def run_cli(argv):
    """命令行模式（支持批量 / 并发 / 暂停 / 取消 / EPUB 选项）：

      单输入  : --cli <链接或路径> [--out 目录] [--title 书名] [--jobs 1-64]
      多输入  : --cli <输入1> <输入2> ... [--out 目录]
      扫文件夹: --cli --dir <文件夹> [--out 目录]
      组合    : --cli <输入1> --dir <文件夹> ... [--out 目录]
      查版本  : --version

    v1.3.0 可选参数：
      --author <作者>  --language <语言>  --tags <标签,逗号分隔>
      --description <描述>  --chapters <分组,如 第1卷:1-20,第2卷:21-40>
      --cover <封面图片路径>  --css <自定义CSS文本>

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

    # v1.3.0 选项参数
    author = take("--author")
    language = take("--language")
    tags = take("--tags")
    description = take("--description")
    chapters = take("--chapters")
    cover = take("--cover")
    css = take("--css")

    inputs = [a for a in args if a.strip() and not a.startswith("--")]
    for d in dirs:
        inputs.extend(scan_dir_for_html(d))

    if not inputs:
        log("用法:")
        log("  单输入  : python telegraph-epub-converter.py --cli <链接或路径> [--out 目录] [--title 书名] [--jobs 1-64]")
        log("  多输入  : python telegraph-epub-converter.py --cli <输入1> <输入2> ... [--out 目录]")
        log("  扫文件夹: python telegraph-epub-converter.py --cli --dir <文件夹> [--out 目录]")
        log("  组合    : python telegraph-epub-converter.py --cli <输入1> --dir <文件夹> ... [--out 目录]")
        log("  查版本  : python telegraph-epub-converter.py --version")
        log("v1.3.0 可选参数:")
        log("  --author <作者>  --language <语言>  --tags <标签,逗号分隔>  --description <描述>")
        log("  --chapters <分组>（如 \"第1卷:1-20,第2卷:21-40\"）")
        log("  --cover <封面图片路径>  --css <自定义CSS文本>")
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
    if author:
        log("作者: %s" % author)
    if language:
        log("语言: %s" % language)
    if tags:
        log("标签: %s" % tags)
    if description:
        log("描述: %s" % description)
    if chapters:
        log("章节分组: %s" % chapters)
    if cover:
        log("自定义封面: %s" % cover)
    if css:
        log("自定义 CSS: %d 字符" % len(css))

    results = convert_batch(inputs, out_dir, title=title, log_cb=log,
                            concurrency=concurrency,
                            pause_event=pause_event, cancel_event=cancel_event,
                            author=author, language=language, tags=tags,
                            description=description, chapters=chapters,
                            cover=cover, css=css)
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
    if "--version" in sys.argv:
        try:
            sys.stdout.write("telegraph_epub_converter v%s\n" % VERSION)
            sys.stdout.flush()
        except Exception:
            pass
        return 0
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
