# telegraph-epub-converter

telegra.ph 漫画网页一键转 EPUB 电子书工具（tkinter GUI + CLI，支持批量转换）。

将 telegra.ph 整页保存的漫画网页（本地 HTML 或在线链接）解析为逐页阅读的漫画版 EPUB：
每页一图、自动生成封面与目录，并做结构校验，可直接导入手机 / 阅读器。

## 功能特性

- 支持本地 HTML 网页保存文件：**无扩展名 / .html / .htm** 均可自动识别
- 支持 telegra.ph 在线链接：自动下载页面 HTML 与全部漫画图片
- 批量转换：
  - GUI：输入列表支持多条（文件多选 / 在线链接 / 扫描文件夹），可增删、清空，逐个转换并汇总成功 / 失败结果
  - CLI：`--cli` 后接多个输入参数，或 `--dir` 扫描文件夹内所有 Telegraph 网页文件
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
4. 点击 `开始批量转换`：逐个转换，进度条实时反馈，完成后弹窗汇总成功 / 失败数量，可一键打开文件或输出目录

### CLI 模式

```bash
# 单输入（可指定书名）
python telegraph_epub_converter.py --cli "<本地路径或在线链接>" [--out <输出目录>] [--title <书名>]

# 多输入批量
python telegraph_epub_converter.py --cli 输入1 输入2 输入3 ... [--out <输出目录>]

# 扫描文件夹批量（自动识别其中所有 Telegraph 网页文件）
python telegraph_epub_converter.py --cli --dir <文件夹> [--out <输出目录>]

# 组合：位置参数 + 多个 --dir 可同时使用
python telegraph_epub_converter.py --cli 输入1 --dir 文件夹A --dir 文件夹B [--out <输出目录>]
```

示例：

```bash
# 三个本地文件批量转换
python telegraph_epub_converter.py --cli "D:\漫画\第1话.html" "D:\漫画\第2话.html" "D:\漫画\第3话.html" --out "D:\EPUB输出"

# 扫描整个文件夹
python telegraph_epub_converter.py --cli --dir "D:\漫画" --out "D:\EPUB输出"

# 在线链接单本转换
python telegraph_epub_converter.py --cli "https://telegra.ph/xxx" --title "我的漫画" --out "D:\EPUB输出"
```

> 批量模式自动取各文件标题作为书名，`--title` 仅对单输入生效。
> 同名输出文件会自动追加 `_1`、`_2` 后缀，不会覆盖已有 EPUB。

## 转换原理

1. **识别输入**：在线链接直接使用；本地路径按 原路径 → `.html` → `.htm` 依次探测
2. **获取页面 HTML**：在线链接用带浏览器 UA 的 urllib 下载；本地文件直接读取
3. **提取图片**：正则按出现顺序提取 `<img src="...">` 外链，过滤为图片地址并去重
4. **下载图片**：逐张下载到临时目录（失败会抛错，由批量流程记录）
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
工具内置 60 秒超时与浏览器 UA。若仍失败，可先手动在浏览器打开链接确认可访问；漫画图片较多时建议网络良好环境转换。批量模式中单个失败不影响其他输入，最终会汇总失败原因。

**Q3：路径含空格、中文、特殊字符（如 `–`、`#`）怎么办？**
建议用引号包裹路径（GUI 模式直接选择文件无需担心）。文件名中的非法字符（`\ / : * ? " < > |` 等）会自动替换为下划线。

**Q4：批量模式书名怎么定的？**
每个输入自动取文件标题（本地文件取文件名，在线链接取链接 slug），输出 EPUB 同名。需要自定义书名时请单本转换并使用 `--title`。

**Q5：EPUB 打不开或提示损坏？**
工具内置结构校验，校验失败会中止并提示原因。若已生成但阅读器不识别，可用 `zipfile` 验证完整性，或尝试用 Calibre 转换一次。

**Q6：转换时界面卡死？**
不会。GUI 的转换在后台线程执行，通过队列向主线程推送进度，界面始终可响应；重复点击转换按钮会提示"正在转换中"。
