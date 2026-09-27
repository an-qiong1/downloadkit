# downloadkit

多平台资源下载工具，支持音乐、视频、图片等多种资源的搜索和下载。

**两套部署方案**：
- 🪟 **Windows 桌面**：Python CLI + 内置 Web UI（静态页面），简单轻量
- 🐳 **NAS Docker**：FastAPI + Celery + Redis + React 前端，适合 NAS 长期运行

> 👉 **只是想用，不想看代码？** 直接看 → **[新手使用说明（图文）](docs/使用说明.md)**
> 双击 exe、扫码登录、订阅创作者，全程带截图，不用装 Python、不用敲命令。

## 功能

- **音乐下载**：网易云音乐、QQ 音乐，支持单曲/批量/歌单导入，MP3 格式带 ID3 标签
- **视频下载**：抖音、B站、YouTube、小红书，无水印下载
- **实况照片**：Google Motion Photo 生成，兼容小米/OPPO/三星等设备相册
- **下载队列**：任务队列管理，支持暂停/恢复/重试/取消
- **下载历史**：SQLite 持久化存储，支持搜索和清理
- **CLI**：命令行工具，支持交互和非交互模式

## 使用方式

### 方案一：Windows 桌面

```bash
git clone https://github.com/an-qiong1/downloadkit.git
cd downloadkit
pip install -e .
```

**Web 界面（推荐）**：
```bash
python run.py
```
浏览器自动打开 `http://127.0.0.1:8765`，搜索、下载、管理文件全在网页上完成。
Windows 用户也可以双击 `start.bat` 启动（自动检测虚拟环境）。

**CLI 命令行**：
```bash
# 搜索歌曲
python -m downloadkit.cli search "晴天"
# 非交互模式：直接指定下载第几首
python -m downloadkit.cli search "晴天" -s 16
# 歌单下载
python -m downloadkit.cli playlist "https://music.163.com/playlist?id=xxx"
# 抖音下载
python -m downloadkit.cli douyin "https://v.douyin.com/xxx"
```

### 方案二：NAS Docker 部署

使用完整的 FastAPI + Celery + Redis + React 前端：

```bash
docker compose -f docker-compose.nas.yml up -d --build
```

访问 `http://<nas-ip>:3000`（前端）或 `http://<nas-ip>:8000`（API）。

如需生产配置（带资源限制）：
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### 方案三：单容器 Docker

轻量部署，使用原始静态前端：

```bash
docker compose up -d --build
```

访问 `http://<host>:8765`。

### 可选依赖

```bash
# 实况照片功能（Pillow + moviepy）
pip install -e ".[media]"
# 浏览器解析功能（Playwright）
pip install -e ".[browser]"
# 开发测试（pytest）
pip install -e ".[dev]"
```

**功能与依赖对照表**：

| 功能 | 必需依赖 | 可选依赖 |
|------|----------|----------|
| 音乐下载 | ✅ | - |
| 视频下载 | ✅ | - |
| 实况照片 | - | `Pillow`, `moviepy` |
| 浏览器解析 | - | `playwright` |

## 下载原理

1. 音乐搜索通过网易云 / QQ 音乐官方 API
2. 音乐下载通过 `itzo.cn` 代理获取真实外链，必要时回退 yt-dlp
3. 视频解析通过各平台 API 或第三方接口

## 项目结构

```
downloadkit/          # 核心 Python 库
├── cli.py            # CLI 入口
├── downloader.py     # 下载引擎
├── download_queue.py # 下载队列
├── platforms/        # 平台适配（netease, qqmusic, itzo, gequbao, migu）
├── static/           # 原始 Web 前端（静态页面，Windows 桌面用）
├── searcher.py       # 聚合搜索
├── playlist.py       # 歌单解析
├── douyin.py         # 抖音解析
├── bilibili.py       # B站解析
├── youtube.py        # YouTube解析
├── xiaohongshu.py    # 小红书解析
├── motion_photo.py   # 实况照片生成
├── history.py        # 下载历史(SQLite)
├── file_manager.py   # 安全文件管理
├── utils.py          # 工具函数
├── exceptions.py     # 异常定义
├── proxy.py          # 代理工具
├── logger.py         # 日志工具
└── browser_cookie.py # Cookie 管理
backend/              # FastAPI 后端（NAS Docker 用）
├── app/
│   ├── api/          # API 路由
│   ├── core/         # 配置、数据库
│   ├── models/       # SQLAlchemy 模型
│   ├── schemas/      # Pydantic 模式
│   ├── services/     # 业务逻辑、平台解析器
│   └── tasks/        # Celery 异步任务
├── Dockerfile
└── requirements.txt
frontend/             # React 前端（NAS Docker 用）
├── src/              # React + Ant Design
├── Dockerfile
└── nginx.conf
server.py             # Web 后端 (FastAPI，Windows 用)
run.py                # 一键启动（Windows）
tests/                # 测试用例
scripts/              # 工具脚本
docs/                 # 文档、设计资料
```

## 配置

### 下载目录

默认下载根目录为 `~/Downloads/DownloadKit`，分类文件夹（`music` /
`videos` / `images` / `animated`）全部收在这个总文件夹里，不会直接散落在
系统下载目录下。旧版默认值（`./downloads`、`~/Downloads`）会在启动时自动
迁移：配置值一次跳到最新默认，磁盘上已有的旧分类目录一次性搬进总文件夹
（同名不覆盖，搬不动的留在原地）。

可通过以下方式修改：

1. **环境变量**：`MUSIC_DL_DIR=/path/to/downloads`（Docker 场景，且此时不做迁移）
2. **配置文件**：`~/.downloadkit/config.toml`
3. **界面**：设置 → 下载目录（改总目录时，没单独自定义过的分类目录会跟着改）

### 代理设置

程序会自动检测系统代理设置。如需手动配置：

```bash
# 环境变量
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

### Cookie 配置

部分平台（如抖音）需要 Cookie 才能正常使用：

1. 在浏览器中登录对应平台
2. 导出 Cookie 文件（JSON 格式）
3. 放置到 `~/.downloadkit/cookies/` 目录

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

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_boundary.py -v

# 运行带覆盖率的测试
pytest --cov=downloadkit
```

### 测试覆盖

- 路径安全测试：28 个用例
- 历史记录测试：6 个用例
- 下载队列测试：10 个用例
- CORS 配置测试：4 个用例

## 常见问题

### Q: 启动后浏览器没有自动打开？

A: 手动访问 `http://127.0.0.1:8765`

### Q: 下载失败怎么办？

A: 
1. 检查网络连接
2. 检查平台是否需要登录/Cookie
3. 尝试使用代理
4. 查看控制台错误信息

### Q: 如何更新到最新版本？

A:
```bash
git pull
pip install -e .
```

### Q: 支持哪些视频平台？

A: 目前支持：
- 抖音/TikTok
- B站
- YouTube
- 小红书

### Q: 下载的文件保存在哪里？

A: 默认在 `~/Downloads/DownloadKit` 目录，按类型分类：
- `~/Downloads/DownloadKit/music/` - 音乐
- `~/Downloads/DownloadKit/videos/` - 视频
- `~/Downloads/DownloadKit/images/` - 图片
- `~/Downloads/DownloadKit/animated/` - 实况照片

### Q: 如何批量下载？

A: 
- Web 界面：使用批量解析功能
- CLI：多次调用命令或编写脚本

## 故障排除

### 编码错误

Windows 用户如遇编码问题，程序会自动尝试修复。如仍有问题：

```bash
# 设置环境变量
set PYTHONIOENCODING=utf-8
```

### 依赖安装失败

```bash
# 升级 pip
python -m pip install --upgrade pip

# 使用国内镜像
pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### FFmpeg 相关错误

B站视频下载需要 FFmpeg：

```bash
# Windows (使用 scoop)
scoop install ffmpeg

# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

## 开发指南

### 添加新平台

1. 在 `downloadkit/platforms/` 创建新文件
2. 实现 `BasePlatform` 接口
3. 在 `downloadkit/platforms/__init__.py` 注册
4. 在 `server.py` 添加路由

### 代码风格

- 使用中文注释
- 遵循 PEP 8
- 使用类型提示
- 编写文档字符串

### 提交规范

```
feat: 添加新功能
fix: 修复问题
docs: 更新文档
test: 添加测试
refactor: 重构代码
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

### v0.4.1 (2026-09-27)

- 🐛 修复创作者订阅「订阅」「预览」报 `DouyinBrowser is not iterable`（实参顺序 + 整段文案当 URL 两层根因）
- 🐛 修复测试脚本 `test-exe-tray.py` 在中文控制台下 UnicodeEncodeError 崩溃
- ✨ 窗口改为 1120×700 并在工作区居中（原来 1280×800 落在左上角）
- ✨ 下载目录归到 `~/Downloads/DownloadKit` 总文件夹，四个分类目录收在里面；
  旧目录启动时自动搬迁（同名不覆盖、搬不动的留原地）
- ✅ 新增 32 个回归用例，全量 249 passed / 6 skipped

### v0.4.0 (2026-09-26)

- ✅ 抖音创作者订阅与自动增量下载（水位线防回补，首次订阅只建基线）
- ✅ 抖音扫码登录与登录态持久化，扫码只需一次
- ✅ 抖音浏览器优先系统 Edge，Playwright 自带 Chromium 兜底
- ✅ Windows exe 一体化打包，playwright driver 随包分发
- ✅ 歌单收藏、ID3 标签写入、设置页目录选择与 Cookie 登录
- ✅ NAS Docker 部署支持与下载目录挂载
- ✅ 统一版本号为 0.4.0（修正安装包误写的 1.0.0）
- ✅ 开机自启动（写 HKCU Run，不弹 UAC）与关闭窗口最小化到托盘（后台常驻不中断订阅检查）
- ✅ 新手使用说明（图文），README 顶部给入口
- ✅ 静态资源引用一致性测试（防止 JS 引用不存在的元素 ID）

### v0.3.1 (2026-06-01)

- ✅ Web UI拆分重构（3500行 → 237行 + 7个模块文件）
- ✅ 提取公共函数check_download_status()消除重复代码
- ✅ 补充测试覆盖（60个测试通过）
- ✅ 补全依赖声明（添加biliup可选依赖）
- ✅ 统一日志框架（使用logging模块）

### v0.3.0 (2026-05-30)

- ✅ 修复文件接口路径安全漏洞
- ✅ 修复下载历史记录功能
- ✅ 统一下载队列管理
- ✅ 限制 CORS 配置
- ✅ 添加边界测试用例
- ✅ 更新文档

### v0.2.0

- 添加小红书下载支持
- 添加实况照片功能
- 优化下载队列

### v0.1.0

- 初始版本
- 支持音乐、视频下载
- Web UI 界面
