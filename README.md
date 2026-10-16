# DownloadKit

多平台资源下载工具：音乐、视频、图文一站下载，带 Web 界面 + 命令行两种用法。

**三套部署形态**（同一仓库，互不通用，详见 [ARCHITECTURE.md](ARCHITECTURE.md)）：

- 🪟 **Windows 桌面版（主线）**：`server.py` + 手写静态 Web UI + 打包 exe，功能最全
- 🐳 **单容器 Docker**：同一套代码，容器里跑
- 🐳 **NAS 多容器 Docker**：`backend/` + `frontend/`（原 media-fetch），功能长期落后主线，改动需两边同步

> 👉 **只是想用，不想看代码？** 直接看 → **[新手使用说明（图文）](docs/使用说明.md)**
> 双击 exe、扫码登录、订阅创作者，全程带截图，不用装 Python、不用敲命令。

## 功能

**下载能力**

- **音乐下载**：网易云、QQ 音乐、歌曲宝、咪咕等多源，**五级回退**（源站直链 → itzo 换链 → 曲库源 → CDN → yt-dlp 兜底），MP3 带 ID3 标签；单曲 / 搜索选曲 / 歌单批量
- **视频下载**：抖音（无水印）、B站、YouTube、小红书，外加 generic 兜底（任意网页/直链）
- **资源解析**：`L0 直链 → L1 yt-dlp 静态解析 → L2 浏览器嗅探` 三层降级；多行输入批量解析、播放页选集展开、多流勾选、解析期 Referer 透传
- **影视解析**：独立主导航 Tab，书签 HTML 导入 → 批量并发探测 → 勾选批量下载，按剧名建子目录
- **创作者订阅**：抖音创作者自动检查更新，水位线防重复；下载范围 `only_new / backfill_n / all`；定时双模式（间隔 / 每天时刻 + 抖动）；卡片显示上次检查状态
- **实况照片**：Google Motion Photo 生成，兼容小米/OPPO/三星等设备相册

**管理能力**

- **下载队列**：暂停/恢复/重试/取消、断点续传、进度保留、一键重试全部失败、完成项点行直接打开文件
- **文件管理**：分类目录浏览、勾选删除、打开目录（全链路路径安全校验）
- **下载历史**：SQLite 持久化，搜索与清理
- **我的歌单**：收藏歌单，一键批量下载

**体验与环境**

- **抖音扫码登录**：登录态持久化，扫码只需一次；浏览器优先系统 Edge，Playwright Chromium 兜底
- **代理三态**：关闭 / 跟随系统 / 手动，可按平台覆盖（YouTube / B站 / 抖音 / 小红书），带测试连接
- **桌面集成**：系统托盘常驻、开机自启、关闭窗口最小化到托盘（订阅检查不中断）、托盘菜单快捷项
- **设置导出/导入**、解答页（FAQ + 报错对照 + 全文搜索）、窗口内一键改下载目录

## 使用方式

### 方案一：Windows 桌面（推荐）

**直接用打包版**：双击 `dist/downloadkit.exe`（无需 Python）。重新打包：

```powershell
powershell -File build\build-release.ps1
```

**从源码跑**：

```bash
git clone https://github.com/an-qiong1/downloadkit.git
cd downloadkit

# 建虚拟环境 + 装依赖（可选 extra 见下表）
python -m venv .venv
.venv\Scripts\pip install -e ".[media,browser,douyin,desktop,dev]"

# 起桌面窗口（WebView2 原生窗口 + 托盘 + 单实例；也可双击 start.bat）
python run.py

# 只想要浏览器访问、不起窗口（无 pywebview 也能跑）
python server.py
```

`python run.py` 会自动开窗口并打开 `http://127.0.0.1:8765`（端口被占会顺延到 8800 内的空闲端口）；
`python server.py` 只起 Web 后端，浏览器自己访问上面的地址即可。
装完环境可以跑一次 `检查环境.bat` 自检（Python 版本、fastapi、pywebview、playwright 内核、WebView2）。

### 方案二：单容器 Docker

同一套 `server.py` + 静态前端，自带资源限制与健康检查，下载目录 bind mount 到 `./downloads`：

```bash
docker compose up -d --build
```

访问 `http://<host>:8765`。

### 方案三：NAS 多容器 Docker

FastAPI + Celery + Redis + React 前端：

```bash
docker compose -f docker-compose.nas.yml up -d --build
```

访问 `http://<nas-ip>:3000`（前端）或 `http://<nas-ip>:8000`（API）。
`docker-compose.prod.yml` 是同一套 NAS 版的常驻配置（重启策略 + 独立卷布局）。

> ⚠️ NAS 版只有 20 条路由（主线 64 条），**没有**订阅 / 视频解析 / 队列 / 设置 / 书签嗅探 /
> 抖音登录 / 文件管理，测试覆盖为 0。差异盘点见 [ARCHITECTURE.md](ARCHITECTURE.md)。

### 可选依赖

```bash
pip install -e ".[media]"    # 实况照片（Pillow + moviepy）
pip install -e ".[browser]"  # 浏览器解析（playwright）
pip install -e ".[douyin]"   # 抖音签名（PyExecJS + gmssl）
pip install -e ".[desktop]"  # 桌面窗口与托盘（pywebview + pystray）
pip install -e ".[dev]"      # 测试（pytest）
```

| 功能 | 必需依赖 | 可选依赖 |
|------|----------|----------|
| 音乐下载 | ✅ | - |
| 视频解析/下载 | ✅ | `playwright`（L2 浏览器嗅探、抖音扫码登录） |
| 实况照片 | - | `Pillow`, `moviepy` |
| 桌面窗口 / 托盘 | - | `pywebview`, `pystray` |

B站视频合并需要系统 `ffmpeg`。

## CLI

入口：`downloadkit`（`pip install -e .` 后）或 `python -m downloadkit.cli`，Windows 下也可用根目录的 `music-dl.cmd`。

| `search <关键词>` | 跨平台搜歌并选曲下载，`-n` 条数、`-s 16 / 1,3 / 1-3` 非交互直选 |
| `playlist <歌单链接>` | 歌单解析 + 批量下载（QQ音乐 / 网易云） |
| `download <歌曲链接>` | 按链接直接下单曲 |
| `douyin <链接或分享文本>` | 抖音无水印下载，`-o` 输出根目录 |
| `parse <链接>` | **只解析不下载**：抖音/B站/YouTube/小红书/任意网页，`--json` 机器可读、`-e` 展开选集、`--referer`、`--name` |
| `video <链接>` | 解析 + 下载，`-q best/1080/720/480/360`、`-o` 输出目录、`-e` + `-n 1,3/1-5/a` 批量选集 |
| `queue …` | 队列管理（需服务在跑）：`list [all/active/done/failed]`、`pause/resume/cancel/retry <id>`、`retry-failed`、`rm <id>`、`open <id>` |
| `subscribe …` | 订阅管理（需服务在跑）：`list`、`add <sec_uid> [-n 名称]`、`rm <creator>`、`scope <creator> [all|history|digg]`、`poller on|off|set <mode>` |
| `files …` | 文件管理（需服务在跑）：`ls [目录]`、`rm <路径...>`、`open <路径>` |
| `sniff <url>` | 资源嗅探（真实浏览器深度抓取），`-t/--timeout L2 预算`、`--json` |
| `bookmarks import <文件>` | 导入浏览器书签 HTML，批量解析出全部可下载链接，`--urls` 去重一行一个管道友好、`-n/--limit` 截断 |
| `settings get [键]` | 设置管理（需服务在跑）：不跟键全量列出、跟键只回值；`set <key> <值>` 改配置；`proxy-test [代理地址] [--url 目标]` 测代理或直连通不通 |
| `collections …` | 收藏歌单管理（需服务在跑）：`list`、`show <ID> [-n 曲目数]`、`add <链接> [-n 名称]`、`rename <ID> <名>`、`rm <ID...>`、`refresh <ID...>` |

```bash
# 搜歌并直接下第 16 首
downloadkit search "晴天" -s 16

# 解析成 JSON 交给其它脚本用
downloadkit parse "https://www.bilibili.com/video/BV..." --json

# 按清晰度下载，产物落到 ./out
downloadkit video "https://youtu.be/xxx" -q 1080 -o ./out

# 展开选集，只下第 1、3 集
downloadkit video "https://www.douyin.com/video/xxx" -e -n 1,3
```

CLI 输出默认压掉 INFO 日志保证管道干净，需要细节时加 `-v`。

`queue` / `subscribe` / `files` / `sniff` / `bookmarks` / `settings` / `collections` 这些命令读写的是**正在运行的服务**（队列/订阅/收藏都在它的内存或 SQLite 里，浏览器的 cookie 更是进程内单例），所以要先起服务；地址默认 `http://127.0.0.1:8765`，换地址用全局 `--server` 或环境变量 `DOWNLOADKIT_SERVER`。

```bash
downloadkit queue list failed          # 看失败了哪些
downloadkit queue retry-failed         # 一键重试全部失败
downloadkit queue open <task_id>       # 打开产物文件并移出列表
```

## 下载原理

1. 音乐搜索走网易云 / QQ 音乐官方接口；下载按**五级回退**逐级尝试（源站 → itzo 换链 → 曲库 → CDN → yt-dlp）
2. 视频按平台分发到 `downloadkit/video_service.py`（`detect_platform` → `parse_url` → `download_parsed`），UI 与 CLI 共用同一套逻辑
3. 通用网页走三层降级：直链识别 → yt-dlp 静态解析 → 浏览器嗅探（DrissionPage + Edge，可过 WAF）
4. 断点续传只对**同一来源 URL** 生效，换源一律重下，避免拼接出坏文件

## 项目结构

```
downloadkit/              # 核心 Python 包
├── cli.py                # CLI 入口（click + rich）
├── video_service.py      # 视频平台分发共享层（server 与 CLI 共用）
├── searcher.py           # 聚合搜索
├── downloader.py         # 下载引擎（多源回退、断点续传）
├── download_queue.py     # 下载队列
├── playlist.py           # 歌单解析
├── platforms/            # 音乐平台适配（netease, qqmusic, itzo, gequbao, migu…）
├── douyin.py             # 抖音解析（API / 浏览器 / 图文 / 实况）
├── douyin_browser.py     # 抖音浏览器后端（扫码登录、订阅抓取）
├── bilibili.py / youtube.py / xiaohongshu.py / generic_video.py
├── subscription.py       # 创作者订阅（水位线、下载范围）
├── subscription_service.py  # 订阅业务（预览、单查、补下）
├── poller.py             # 定时检查（间隔 / 每天时刻 + 抖动 + 退避）
├── motion_photo.py       # 实况照片生成
├── history.py            # 下载历史（SQLite）
├── file_manager.py       # 路径安全
├── proxy.py              # 代理三态与平台覆盖
├── browser_cookie.py     # Cookie 管理
└── static/               # Web 前端（手写 HTML/CSS/JS，主线用）
server.py                 # Web 后端（FastAPI，64 条路由）
run.py                    # 桌面启动（WebView2 窗口 + 托盘 + 单实例）
backend/  frontend/       # NAS 多容器版（FastAPI+Celery+Redis / React+AntD）
build/                    # 打包与验收脚本（build-release.ps1、test-exe-*）
tests/                    # 测试用例（1006 passed / 6 skipped）
docs/                     # 使用说明（图文）、验证与优化报告
PLAN.md                   # 当前开发计划与进度（交接文档）
ARCHITECTURE.md           # 架构与三套部署形态判别
DEVELOPMENT.md            # 开发环境、加平台、发版流程
CHANGELOG.md              # 更新日志
```

## 配置

### 下载目录

默认下载根目录为 `~/Downloads/DownloadKit`，分类文件夹（`music` / `videos` / `images` / `animated`）
都收在这个总文件夹里。旧版默认值（`./downloads`、`~/Downloads`）会在启动时自动迁移：
配置值一次跳到最新默认，磁盘上已有的旧分类目录一次性搬进总文件夹（同名不覆盖，搬不动的留原地）。

修改方式：

1. **界面**：设置 → 下载目录（改总目录时，没单独自定义过的分类目录会跟着改；4 个分类目录收在「高级」折叠里）
2. **配置文件**：`~/.downloadkit/config.toml`
3. **环境变量**：`MUSIC_DL_DIR=/path/to/downloads`（Docker 场景，此时不做迁移）
4. **设置页导出/导入**：配置可备份成 JSON 再导入

### 代理设置

程序自动检测系统代理；界面里可切 `关闭 / 跟随系统 / 手动`，手动支持按平台覆盖并「测试连接」。

```bash
# 或用环境变量
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

### Cookie 配置

部分平台（如抖音）需要登录态：

1. **推荐**：设置页 → 抖音扫码登录（登录态持久化，只需一次）
2. 或在浏览器登录后导出 Cookie（JSON），放到 `~/.downloadkit/cookies/`

## 安全特性

### 路径安全

所有文件接口都经过安全验证，防止路径遍历攻击：

- 自动检测 `../`、`%2e%2e` 等遍历模式
- 限制文件操作在下载目录内
- 阻止绝对路径访问

### CORS 配置

默认只允许本地访问：

```python
allow_origins = ["http://127.0.0.1:8765", "http://localhost:8765"]
```

如需局域网访问，请修改 `server.py` 中的 CORS 配置。

## 测试

```bash
# 全量（当前 1006 passed / 6 skipped）
$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest tests -q

# 指定用例
pytest tests/test_boundary.py -v

# 覆盖率
pytest --cov=downloadkit
```

打包版验收（发版前固定跑）：

```powershell
powershell -File build\build-release.ps1   # 重打包
build\test-exe.ps1                          # API 冒烟
python build\test-exe-tray.py               # 托盘 33 项
python build\test-exe-douyin.py             # 抖音 9 项
```

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/使用说明.md](docs/使用说明.md) | 新手图文教程（exe、扫码登录、订阅） |
| [PLAN.md](PLAN.md) | 下一阶段开发计划与逐条进度（交接文档） |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 分层架构、三套部署形态判别、功能落差 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 环境搭建、加新平台、调试与发版 |
| [CHANGELOG.md](CHANGELOG.md) | 更新日志 |

## 常见问题

### Q: 启动后浏览器没有自动打开？

A: 手动访问 `http://127.0.0.1:8765`（被占用时看 `downloadkit.log` 里的实际端口）。

### Q: 下载失败怎么办？

A:
1. 检查网络连接，或在设置页试一下代理「测试连接」
2. 确认该平台是否需要登录/Cookie（抖音建议直接扫码登录）
3. 设置 → 解答页里有 FAQ 与报错对照表

### Q: 支持哪些视频平台？

A: 抖音/TikTok、B站、YouTube、小红书，以及任意网页（generic + 浏览器嗅探兜底）。

### Q: 下载的文件保存在哪里？

A: 默认在 `~/Downloads/DownloadKit`，按类型分：`music/` `videos/` `images/` `animated/`。

### Q: 如何批量下载？

A:
- 资源解析/影视解析页：多行输入框，一行一条链接，回车批量解析入队
- 书签导入：导入浏览器书签 HTML，按文件夹勾选批量探测下载
- CLI：`video -e -n 1-5` 展开选集批量，或写脚本循环调用

### Q: 如何更新到最新版本？

A:
```bash
git pull
.venv\Scripts\pip install -e .
```
exe 用户重新执行 `build\build-release.ps1` 打包即可。

## 故障排除

### 编码错误

Windows 控制台如遇中文乱码/编码报错：

```powershell
$env:PYTHONIOENCODING='utf-8'
```

### 依赖安装失败

```bash
python -m pip install --upgrade pip
pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### FFmpeg 相关错误

B站视频合并需要 FFmpeg：

```bash
scoop install ffmpeg    # Windows
brew install ffmpeg     # macOS
sudo apt install ffmpeg # Ubuntu/Debian
```

## 开发指南

详细流程见 [DEVELOPMENT.md](DEVELOPMENT.md)，要点：

- **加新平台**：`downloadkit/platforms/` 新建适配器 → `platforms/__init__.py` 注册 → `server.py` 加路由 → 补测试
- **代码风格**：中文注释、PEP 8、类型提示、文档字符串
- **提交规范**：`feat:` / `fix:` / `docs:` / `test:` / `refactor:`；中文提交信息用 `git commit -F 文件` 写入，避免编码损坏

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

完整记录见 [CHANGELOG.md](CHANGELOG.md)，最近两版摘要：

### v0.5.0 (2026-10-04)

- ✅ 批量资源嗅探下载（L0/L1/L2 三层降级、书签导入批量探测、播放页选集展开、选流勾选、深度嗅探）
- ✅ 影视解析独立成主导航 Tab，支持手动输入多行批量
- ✅ 代理三态与平台覆盖 + 测试连接、队列一键重试全部失败、设置导出/导入、解答页搜索、托盘快捷项
- 🐛 修复打包版解析超 2 分钟 + 弹「已在运行」（frozen 下误 spawn 应用本体当 yt-dlp）

### 未发布（2026-10-16 开发中）

- ✨ CLI 新增队列 `queue`（P5-2）、订阅 `subscribe`（P5-3）、文件管理 `files`（P5-4）、资源嗅探与书签导入 `sniff` / `bookmarks`（P5-5）、设置 `settings`（P5-6）、收藏歌单 `collections`（P5-7）——此前这些只能在界面里做，现在 CLI 也能管
- 🐛 歌单收藏模块修两个真 bug（P5-7 实测挖出）：`refresh_collection` 的 SELECT 少了 `auto_name` → 必挂 IndexError，**`POST /api/collections/{id}/refresh` 从来就没工作过**；`_run_async` 把解析器的 RuntimeError 换成 `asyncio.run() cannot be called from a running event loop`，DrissionPage 一抛错用户看到的全是驴唇不对马嘴的报错
- ✨ 历史 `history` 部分已完成：先补服务端 5 个 `/api/history/*` 端点，再补 CLI `list/search/rm/clear/count`（P5-7b）
