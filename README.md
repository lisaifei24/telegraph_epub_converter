---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 7e577fda4eb3f93d3f58265fe8d82685_ef667eafbb8311f18442525400de85a5
    ReservedCode1: UOF6V+EC9L0G2yuO0CAm+8wPYKIut1f+5LydqIa+YbF+e85Y5OA6kZEmj5r3mrSj4EYrXvqQ4WND9BfnAGGKXEuM56psqspP8BHcms0g8l9GeU5Rhb6YhBJ8tWDT4VYVCPijJjIEPfzbzQY8rMfRGXSYXz0JaxIzjtNAkL6rM4Wdox8wLkyfxakRLpA=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 7e577fda4eb3f93d3f58265fe8d82685_ef667eafbb8311f18442525400de85a5
    ReservedCode2: UOF6V+EC9L0G2yuO0CAm+8wPYKIut1f+5LydqIa+YbF+e85Y5OA6kZEmj5r3mrSj4EYrXvqQ4WND9BfnAGGKXEuM56psqspP8BHcms0g8l9GeU5Rhb6YhBJ8tWDT4VYVCPijJjIEPfzbzQY8rMfRGXSYXz0JaxIzjtNAkL6rM4Wdox8wLkyfxakRLpA=
---





# telegraph-epub-converter

telegra.ph 漫画网页一键转 EPUB 电子书工具（tkinter GUI + CLI，支持批量转换）。

将 telegra.ph 整页保存的漫画网页（本地 HTML 或在线链接）解析为逐页阅读的漫画版 EPUB：
每页一图、自动生成封面与目录，并做结构校验，可直接导入手机 / 阅读器。

## 功能特性

- 支持本地 HTML 网页保存文件：**无扩展名 / .html / .htm** 均可自动识别；整页保存（含同名 `_files` 图片目录）的相对路径图片自动解析，不再漏图
- 支持 telegra.ph 在线链接：自动下载页面 HTML 与全部漫画图片
- 批量转换：
  - GUI：输入列表支持多条（文件多选 / 在线链接 / 扫描文件夹），可增删、清空，逐个转换并汇总成功 / 失败 / 取消结果
  - CLI：`--cli` 后接多个输入参数，或 `--dir` 扫描文件夹内所有 Telegraph 网页文件
- **图片并发下载**：默认 16 线程并发下载全部图片（可按需配置 1-64），显著提升批量漫画下载速度；下载失败自动重试 3 次（逐步退避）
- **暂停 / 继续**：转换过程中可随时暂停（下载与打包均暂停）、随时继续
- **取消**：转换中可取消当前及后续任务，取消后自动清理临时文件，已完成的输出保留、未完成的标记为「已取消」
- 提取漫画原图（保持清晰度），按页面顺序逐页排版，生成 EPUB3（含 NCX 兼容老阅读器）
- 输出 EPUB 自动结构校验（mimetype / container / opf / 页面 / 图片引用 / zip 完整性）
- **纯标准库实现**（urllib 下载、zipfile 手写 EPUB3），零第三方依赖

## 安装

无第三方依赖。仅需 Python 3.8+（Windows 官方安装包自带 tkinter）。

```bash
# 可选：验证环境
python --version
python -c "import tkinter, zipfile, urllib.request"
```

### Windows 免安装版（exe）

**v1.1.0 已发布 Release**，提供 Windows 免安装 exe 直接下载：

- 下载地址：[telegraph_epub_converter.exe](https://github.com/lisaifei24/telegraph_epub_converter/releases/download/v1.1.0/telegraph_epub_converter.exe)（约 12.2MB，免安装、无需 Python 环境）
- SHA-256：`8965824031792FFBBFAEC7B8035D26852E75706FA00910A35C2BC0E8A338D1EB`
- Release 页面：https://github.com/lisaifei24/telegraph_epub_converter/releases/tag/v1.1.0
- 功能简介：支持 GUI / CLI 双模式、批量转换、图片并发下载、暂停 / 取消等全部功能；v1.1.0 新增本地整页保存图片（相对路径 `_files` 目录）解析支持，修复本地 HTML 转换提示"未找到任何漫画图片"的问题

## 使用

### GUI 模式

```bash
python telegraph_epub_converter.py
```

窗口操作步骤：

1. **① 输入列表**：通过以下任一方式添加输入（可多条，转换时逐个处理）
   - `添加文件...`：多选本地 HTML / 无扩展名网页文件
   - `添加链接...`：粘贴 telegra.ph 在线链接（每行一个，可一次添加多个）
   - `添加文件夹(扫描)...`：选择文件夹，自动扫描其中所有 Telegraph 网页文件并批量加入
   - `删除选中` / `清空`：维护列表
2. **② 输出目录**：选择 EPUB 输出位置（默认 `下载` 文件夹）
3. **③ 书名**（可选）：仅单个输入时生效；批量时自动取各文件标题
4. 点击 `开始批量转换`：逐个转换，进度条实时反馈；转换过程中可点击 `暂停/继续` 随时挂起与恢复（下载与打包都会暂停），点击 `取消` 立即停止当前及后续任务（已完成的输出保留、未完成的标记为「已取消」，临时文件自动清理）；完成后弹窗汇总成功 / 失败 / 取消数量，可一键打开文件或输出目录

### CLI 模式

```bash
# 单输入（可指定书名、并发数）
python telegraph_epub_converter.py --cli "<本地路径或在线链接>" [--out <输出目录>] [--title <书名>] [--jobs 1-64]

# 多输入批量
python telegraph_epub_converter.py --cli 输入1 输入2 输入3 ... [--out <输出目录>]

# 扫描文件夹批量（自动识别其中所有 Telegraph 网页文件）
python telegraph_epub_converter.py --cli --dir <文件夹> [--out <输出目录>]

# 组合：位置参数 + 多个 --dir 可同时使用
python telegraph_epub_converter.py --cli 输入1 --dir 文件夹A --dir 文件夹B [--out <输出目录>]
```

> 转换过程中：**Ctrl+C** 优雅取消（清理临时文件、标记未完成任务为「已取消」）；**Ctrl+Break** 暂停 / 继续（Windows；类 Unix 下为 Ctrl+Z）。
> `--jobs 1-64` 控制图片并发下载线程数，默认 16；批量模式下暂停 / 取消对后续任务同样生效。

示例：

```bash
# 三个本地文件批量转换
python telegraph_epub_converter.py --cli "D:\漫画\第1话.html" "D:\漫画\第2话.html" "D:\漫画\第3话.html" --out "D:\EPUB输出"

# 扫描整个文件夹
python telegraph_epub_converter.py --cli --dir "D:\漫画" --out "D:\EPUB输出"

# 在线链接单本转换（指定 8 线程并发）
python telegraph_epub_converter.py --cli "https://telegra.ph/xxx" --title "我的漫画" --out "D:\EPUB输出" --jobs 8
```

> 批量模式自动取各文件标题作为书名，`--title` 仅对单输入生效。
> 同名输出文件会自动追加 `_1`、`_2` 后缀，不会覆盖已有 EPUB。

## 转换原理

1. **识别输入**：在线链接直接使用；本地路径按 原路径 → `.html` → `.htm` 依次探测
2. **获取页面 HTML**：在线链接用带浏览器 UA 的 urllib 下载；本地文件直接读取
3. **提取图片**：正则按出现顺序提取 `<img src="...">`；本地文件中的相对路径引用（如 `./xxx_files/0001.webp`）自动解析为绝对路径，网络外链按原样处理，过滤为图片地址并去重
4. **下载图片**：多线程并发下载到临时目录（默认 16 线程，`--jobs` 可配），瞬时网络错误自动重试 3 次（逐步退避），下载完成后严格按页面顺序写回 EPUB；任一图片最终失败则该本转换失败（不静默跳过），由批量流程汇总记录
5. **生成 EPUB**：纯 `zipfile` 手写 EPUB3：
   - `mimetype`（不压缩，必须第一个条目）
   - `META-INF/container.xml`
   - `EPUB/content.opf`（manifest + spine + 封面 + 逐页目录）
   - `EPUB/nav.xhtml`（EPUB3 目录导航）+ `EPUB/toc.ncx`（EPUB2 兼容）
   - `EPUB/cover.xhtml`（封面页）+ 每页 `page_XXX.xhtml`（每页一图）
   - `EPUB/images/`（内嵌原图，保持清晰度）
6. **结构校验**：检查 mimetype / container / opf / 页面完整性 / 图片引用 / zip 无损

## 常见问题

**Q1：本地保存的 telegra.ph 网页没有扩展名，能识别吗？**
能。`resolve_input` 会自动尝试补 `.html` / `.htm`，无扩展名文件本身也会被识别为本地文件。扫描文件夹时，无扩展名文件只要文件名含 `telegraph` 或文件头包含 `telegra.ph` 即被纳入。

**Q2：在线链接下载失败或很慢？**
工具内置 60 秒超时与浏览器 UA，图片多线程并发下载（默认 16 线程，可用 `--jobs` 调整），瞬时网络错误自动重试 3 次。若仍失败，可先手动在浏览器打开链接确认可访问；漫画图片较多时建议网络良好环境转换。批量模式中单个失败不影响其他输入，最终会汇总失败原因。

**Q3：路径含空格、中文、特殊字符（如 `–`、`#`）怎么办？**
建议用引号包裹路径（GUI 模式直接选择文件无需担心）。文件名中的非法字符（`\ / : * ? " < > |` 等）会自动替换为下划线。

**Q4：批量模式书名怎么定的？**
每个输入自动取文件标题（本地文件取文件名，在线链接取链接 slug），输出 EPUB 同名。需要自定义书名时请单本转换并使用 `--title`。

**Q5：EPUB 打不开或提示损坏？**
工具内置结构校验，校验失败会中止并提示原因。若已生成但阅读器不识别，可用 `zipfile` 验证完整性，或尝试用 Calibre 转换一次。

**Q6：转换时界面卡死？**
不会。GUI 的转换在后台线程执行，通过队列向主线程推送进度，界面始终可响应；转换中可用 `暂停/继续` 挂起、`取消` 终止（当前及后续任务，已完成的输出保留）；重复点击转换按钮会提示"正在转换中"。

**Q7：本地整页保存的 Telegraph HTML 转换时提示"未找到任何漫画图片"？**
这是旧版（v1.0.0 及之前）的已知问题：整页保存的网页图片存放在同名 `_files` 目录中，`<img>` 使用的是 `./xxx_files/0001.webp` 这类本地相对路径，旧版只匹配 `http(s)` 外链导致全部漏掉。v1.1.0 已支持相对路径图片解析（含 `.webp` / `.avif` 等扩展名），升级即可修复。
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
