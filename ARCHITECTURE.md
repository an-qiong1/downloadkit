# DownloadKit 架构文档

## 概述

DownloadKit 是一个多平台资源下载工具，采用前后端分离架构，支持音乐、视频、实况照片等多种资源的下载。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户界面层                              │
├─────────────────────────────────────────────────────────────┤
│  Web UI (index.html + CSS + JS模块)                         │
│  CLI (cli.py)                                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      服务层                                  │
├─────────────────────────────────────────────────────────────┤
│  FastAPI后端 (server.py)                                    │
│  ├── 音乐API                                                │
│  ├── 视频API                                                │
│  ├── 文件管理API                                            │
│  └── 下载队列API                                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      业务逻辑层                              │
├─────────────────────────────────────────────────────────────┤
│  searcher.py (聚合搜索)                                     │
│  downloader.py (下载引擎)                                   │
│  playlist.py (歌单解析)                                     │
│  download_queue.py (下载队列)                               │
│  history.py (下载历史)                                      │
│  motion_photo.py (实况照片)                                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      平台适配层                              │
├─────────────────────────────────────────────────────────────┤
│  platforms/                                                 │
│  ├── base.py (抽象基类)                                     │
│  ├── netease.py (网易云音乐)                                │
│  ├── qqmusic.py (QQ音乐)                                   │
│  ├── itzo.py (itzo.cn下载源)                                │
│  ├── gequbao.py (歌曲宝下载源)                              │
│  └── migu.py (咪咕音乐)                                     │
│                                                             │
│  视频平台:                                                  │
│  ├── douyin.py (抖音)                                       │
│  ├── bilibili.py (B站)                                     │
│  ├── youtube.py (YouTube)                                  │
│  └── xiaohongshu.py (小红书)                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      基础设施层                              │
├─────────────────────────────────────────────────────────────┤
│  utils.py (工具函数)                                        │
│  logger.py (日志管理)                                       │
│  file_manager.py (文件安全)                                 │
│  proxy.py (代理配置)                                        │
│  browser_cookie.py (浏览器Cookie)                           │
│  exceptions.py (自定义异常)                                 │
└─────────────────────────────────────────────────────────────┘
```

## 模块职责

### 用户界面层

#### Web UI
- **index.html**: 主页面结构（237行）
- **css/main.css**: 样式定义（1438行）
- **js/**: JavaScript模块
  - `utils.js`: 工具函数（$, $$, api, toast等）
  - `music.js`: 音乐搜索/下载模块
  - `resource.js`: 资源解析模块
  - `files.js`: 文件管理模块
  - `queue.js`: 下载队列模块
  - `app.js**: 初始化和侧边栏

#### CLI
- `cli.py`: 命令行入口（click + rich）
  - `search` / `playlist` / `download` / `douyin`：音乐与视频下载
  - `parse` / `video`：视频平台解析 + 下载（抽共享层 `video_service.py`）
  - `queue …`：队列管理（走 HTTP，服务在跑）
  - `subscribe …`：订阅管理（走 HTTP，服务在跑）
  - `files …`：文件管理（走 HTTP，服务在跑）
  - `sniff <url>`：真实浏览器深度资源嗅探（L2）
  - `bookmarks import <文件>`：批量导入书签 HTML 并解析出链接
  - `settings get/set/proxy-test`：设置读取、写入、代理连通性测试（走 HTTP）
  - `collections …`：收藏歌单 CRUD（走 HTTP，服务端缓存在 `~/.downloadkit/collections.db`）

### 服务层

#### FastAPI后端 (server.py)
- 提供RESTful API
- 处理前端请求
- 管理下载任务

### 业务逻辑层

#### searcher.py
- 聚合多个平台的搜索结果
- 按平台优先级和匹配度排序

#### downloader.py
- 下载引擎
- 支持断点续传
- 多源回退策略

#### playlist.py
- 歌单链接解析
- 支持网易云/QQ音乐

#### download_queue.py
- 下载队列管理
- 并发控制
- 暂停/恢复/取消

#### history.py
- SQLite 持久化存储下载记录
- `DownloadHistory` 模块提供 `get_records` / `search_records` / `delete_record` / `clear_history` / `get_total_count` 等读写能力
- **注意**：HTTP 层（`server.py`）目前只调 `add_record` 写入，**没有暴露任何读取端点**，前端也没有历史 UI；CLI 同样没有 `history` 命令（见 PLAN.md P5-7 历史部分）

#### motion_photo.py
- Google Motion Photo生成
- Apple Live Photo转换

### 平台适配层

#### 音乐平台
- `base.py`: 抽象基类定义
- `netease.py`: 网易云音乐API
- `qqmusic.py`: QQ音乐API
- `itzo.py`: itzo.cn下载源
- `gequbao.py`: 歌曲宝下载源
- `migu.py`: 咪咕音乐

#### 视频平台
- `douyin.py`: 抖音解析（1180行）
  - 官方API解析
  - 第三方API解析
  - 浏览器解析（Playwright）
- `bilibili.py`: B站解析
  - DASH格式分离
  - FFmpeg合并
- `youtube.py`: YouTube解析（基于yt-dlp）
- `xiaohongshu.py`: 小红书解析

### 基础设施层

#### utils.py
- `sanitize_filename()`: 文件名清理
- `get_download_dir()`: 获取下载目录
- `download_file()`: 通用下载函数
- `check_download_status()`: 检查暂停/取消状态

#### logger.py
- 统一日志配置
- 控制台/文件输出

#### file_manager.py
- 路径安全验证
- 防止路径遍历攻击

#### proxy.py
- 代理配置检测
- 环境变量/系统代理

#### browser_cookie.py
- 浏览器Cookie获取
- 支持Chrome/Firefox/Edge

#### exceptions.py
- `PauseException`: 暂停异常
- `CancelException`: 取消异常

## 数据流

### 音乐下载流程
```
用户输入 → searcher.py搜索 → 选择歌曲 → downloader.py下载
                                          ↓
                                  platforms/*获取URL
                                          ↓
                                  utils.download_file()
                                          ↓
                                  保存到downloads/music/
```

### 视频下载流程
```
用户输入链接 → 平台检测 → 对应平台解析 → 获取下载URL
                                          ↓
                                  utils.download_file()
                                          ↓
                                  保存到downloads/videos/
```

## 安全设计

### 路径安全
- 所有文件接口经过`file_manager.py`验证
- 防止`../`、`%2e%2e`等路径遍历攻击
- 限制文件操作在下载目录内

### CORS配置
- 默认只允许本地访问
- 防止跨域请求

### 异常处理
- 自定义异常类型
- 统一错误处理

## 测试策略

### 单元测试
- 路径安全测试（34个）
- 下载队列测试（12个）
- 搜索模块测试（6个）
- 歌单解析测试（7个）
- 下载模块测试（5个）

### 测试命令
```bash
# 运行所有测试
pytest -q

# 运行特定测试
pytest tests/test_boundary.py -v
```

## 依赖管理

### 核心依赖
- httpx: HTTP客户端
- fastapi: Web框架
- uvicorn: ASGI服务器
- pydantic: 数据验证
- click: CLI框架
- rich: 终端美化

### 可选依赖
- media: Pillow, moviepy（实况照片）
- browser: playwright（浏览器解析）
- douyin: biliup（抖音签名）
- dev: pytest, pytest-asyncio, pytest-httpx

## 部署

### 三套部署方案

项目存在**三套并行的部署形态**，不要互相误判为「死代码」：

| 方案 | 入口 | 前端 | 后端 | 依赖声明 |
|---|---|---|---|---|
| **Windows 桌面版** | `run.py` / `start.bat` | `downloadkit/static/`（手写 HTML/JS，约 8.7k 行） | `server.py`（64 条路由） | `pyproject.toml`（下限约束） |
| **单容器 Docker** | `docker-compose.yml` → `Dockerfile` | 同上 | 同上 | 同上 |
| **NAS 多容器 Docker** | `docker-compose.nas.yml` / `docker-compose.prod.yml` | `frontend/`（React + AntD） | `backend/`（FastAPI + Celery + Redis，20 条路由） | `backend/requirements.txt`（钉死版本） |

历史由来：提交 `2106062`（2026-07-12）「合并 downloadkit（Windows 桌面版）和 media-fetch（NAS Docker 版）」，
`backend/` + `frontend/` 即原 media-fetch 项目，`frontend/package.json` 的 name 仍是 `media-fetch-frontend`。

**怎么判断一份代码属于哪套**：

- 引用关系在 **`docker-compose*.yml` 的 `build:`** 里，不在 Python import 里 ——
  全仓搜 `from backend` 一定是 0，这不代表它是死代码。
- 依赖清单是**分开的**：Windows 版看 `pyproject.toml`，NAS 版看 `backend/requirements.txt`。
  后者的 `sqlalchemy` / `celery` / `redis` / `pydantic-settings` 属于 NAS 专用，**故意不进** `pyproject.toml`。
- `docker-compose.yml`（无后缀）是单容器版，跑的是 `server.py`，**与 `docker-compose.nas.yml` 不是一套**。

**当前功能落差（2026-10-14 盘点）**：NAS 版长期落后于 Windows 版，改功能时若要 NAS 也生效，必须两边同步。

| 能力 | Windows 版 | NAS 版 |
|---|---|---|
| 路由总数 | 64 | 20 |
| 订阅 / 视频解析 / 队列 / 设置 / 书签嗅探 / 抖音登录 / 文件管理 / Cookies | 有 | **无** |
| `douyin.py` | 2488 行 | 78 行（差 31.9x） |
| `bilibili.py` / `youtube.py` / `collection` | 397 / 265 / 313 行 | 173 / 131 / 84 行 |
| 测试覆盖 | 46 个测试文件 | **0** |

### 开发环境
```bash
pip install -e ".[dev]"
python run.py
```

### 生产环境
```bash
pip install -e .
python run.py --host 0.0.0.0 --port 8765
```

### NAS 多容器
```bash
docker compose -f docker-compose.nas.yml up -d --build
```

## 扩展指南

### 添加新平台
1. 在`downloadkit/platforms/`创建新文件
2. 实现`BasePlatform`接口
3. 在`downloadkit/platforms/__init__.py`注册
4. 在`server.py`添加路由

### 添加新功能
1. 在`downloadkit/`创建新模块
2. 在`server.py`添加API端点
3. 在前端添加UI组件
4. 编写测试用例
