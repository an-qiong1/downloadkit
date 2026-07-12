# Media Fetch — 多平台音视频下载管理系统

> 版本: v1.0
> 日期: 2026-05-25
> 项目路径: `D:\Dowland\media-fetch\`

---

## 1. 项目概述

Media Fetch 是一个基于 Web 的多平台音视频下载管理系统。通过第三方解析和爬虫方式，免费下载互联网上的音乐和视频资源，用于个人媒体库的构建。支持音乐搜索/链接下载、歌单批量下载、抖音去水印+动态照片、YouTube/Bilibili 下载、全网影视资源搜索等功能。

**目标用户**：个人自用，不涉及任何形式的传播与分享。

---

## 2. 三阶段开发路径

### 🔴 第一阶段：音乐 + 抖音下载（核心）

| 平台 | 功能 |
|------|------|
| 网易云音乐 | 搜索下载 + 链接下载 + 歌单批量下载 + ID3元数据 |
| QQ 音乐 | 搜索下载 + 链接下载 + 歌单批量下载 + ID3元数据 |
| Spotify | 搜索下载 + 播放列表批量下载 + 元数据匹配嵌入 |
| 抖音 | 单视频无水印下载 + 主页/合集批量 + 动态照片(Live Photo)识别 |

### 🟡 第二阶段：YouTube + Bilibili

| 平台 | 功能 |
|------|------|
| YouTube | 视频/音乐最高质量下载 + 播放列表批量 |
| Bilibili | 视频/音乐下载 + 合集批量 |

### 🟢 第三阶段：全网影视资源搜索

| 来源 | 方式 |
|------|------|
| YouTube / Bilibili 搬运 | 自动搜索标题匹配的视频资源，通过 yt-dlp 下载 |
| BT 磁力搜索引擎 | 集成多个 BT 搜索引擎，获取磁力链接，通过 aria2 下载 |

**交互逻辑**：输入影视名称 → 自动在 YouTube + Bilibili + BT 搜索 → 汇总结果列表 → 用户选择 → 下载。

---

## 3. 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 后端框架 | Python 3.11+ / FastAPI | 异步 Web 框架 |
| 任务队列 | Celery + Redis | 异步下载任务管理、进度推送 |
| 下载引擎 | yt-dlp（主）+ aria2（磁力） | 核心下载工具 |
| 音视频处理 | FFmpeg | 转码、提取音频、元数据写入 |
| 数据库 | SQLite（开发）→ PostgreSQL（生产） | Alembic 迁移管理 |
| 缓存/队列 | Redis 7+ | Celery Broker + 进度缓存 |
| 前端 | React 18 + Vite + TypeScript + Ant Design 5 | SPA 应用 |
| 实时通信 | WebSocket (FastAPI + 前端原生 WS) | 下载进度实时推送 |
| 容器化 | Docker + Docker Compose | 一键部署 |

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    浏览器 (React SPA)                        │
│  搜索/导入  │  下载管理  │  媒体库  │  播放器  │  设置       │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP REST + WebSocket
┌──────────────────────▼──────────────────────────────────────┐
│                    FastAPI 后端                              │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ API 路由 │  │ WebSocket    │  │ 解析器工厂             │ │
│  │ (REST)   │  │ 进度推送     │  │ (平台无关接口)         │ │
│  └────┬─────┘  └──────┬───────┘  └────────┬──────────────┘ │
│       │               │                    │                │
│  ┌────▼───────────────▼────────────────────▼──────────────┐ │
│  │              Celery Worker 集群                         │ │
│  │  ┌──────────┐  ┌───────────┐  ┌────────────┐          │ │
│  │  │ yt-dlp   │  │ 第三方API │  │ FFmpeg    │          │ │
│  │  │ 下载器   │  │ 解析器    │  │ 后处理    │          │ │
│  │  └──────────┘  └───────────┘  └────────────┘          │ │
│  │  ┌──────────┐  ┌───────────┐                           │ │
│  │  │ aria2    │  │ BT搜索    │                           │ │
│  │  │ 磁力下载 │  │ 聚合引擎  │                           │ │
│  │  └──────────┘  └───────────┘                           │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                       Redis 服务                             │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                       SQLite / PostgreSQL                    │
│   下载任务表  │  媒体库表  │  平台配置表  │  用户表          │
└─────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                    文件存储系统                               │
│  D:\Dowland\media-fetch\media\video\                       │
│  D:\Dowland\media-fetch\media\music\                       │
│  D:\Dowland\media-fetch\media\temp\                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 数据库模型

### 5.1 下载任务表 (download_tasks)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| url | TEXT | 原始 URL |
| platform | VARCHAR(50) | 平台枚举 |
| title | VARCHAR(500) | 解析标题 |
| type | VARCHAR(20) | video / music / live_photo |
| format_id | VARCHAR(100) | 格式 ID |
| status | VARCHAR(20) | pending / downloading / completed / failed |
| progress | FLOAT | 0.0 - 100.0 |
| file_path | TEXT | 文件路径 |
| file_size | BIGINT | 文件大小 |
| error_message | TEXT | 失败原因 |
| created_at | DATETIME | 创建时间 |
| completed_at | DATETIME | 完成时间 |

### 5.2 媒体库表 (media_items)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| task_id | UUID | 关联任务 |
| title | VARCHAR(500) | 标题 |
| artist | VARCHAR(200) | 艺术家 |
| album | VARCHAR(200) | 专辑 |
| duration | INT | 时长(秒) |
| platform | VARCHAR(50) | 来源平台 |
| type | VARCHAR(20) | video / music / live_photo |
| file_path | TEXT | 文件路径 |
| file_size | BIGINT | 大小 |
| tags | TEXT | JSON 标签 |
| cover_path | TEXT | 封面路径 |
| bitrate | INT | 码率 |
| resolution | VARCHAR(20) | 分辨率 |
| file_hash | VARCHAR(64) | 去重哈希 |
| created_at | DATETIME | 入库时间 |

### 5.3 平台配置表 (platform_configs)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| platform | VARCHAR(50) | 平台名 |
| config_key | VARCHAR(100) | cookie / cookies_file |
| config_value | TEXT | 加密存储的值 |

### 5.4 用户表 (users) — 单用户可省略

---

## 6. API 接口设计

### 6.1 下载相关
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/downloads/parse` | 解析 URL → 返回可用格式列表 |
| POST | `/api/downloads/create` | 创建下载任务 |
| GET | `/api/downloads` | 任务列表(分页) |
| GET | `/api/downloads/{id}` | 任务详情 |
| POST | `/api/downloads/{id}/cancel` | 取消 |
| POST | `/api/downloads/{id}/retry` | 重试 |

### 6.2 搜索 + 批量
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/search` | 跨平台搜索音乐(同时搜网易云/QQ/Spotify) |
| POST | `/api/playlists/parse` | 解析歌单/播放列表链接 |
| POST | `/api/playlists/batch-download` | 批量下载选中条目 |
| POST | `/api/media-library/search` | 影视资源全网搜索 |

### 6.3 媒体库
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/media` | 媒体库列表(分页/搜索/筛选) |
| GET | `/api/media/{id}` | 媒体详情 |
| GET | `/api/media/{id}/stream` | 流式播放 |
| GET | `/api/media/{id}/cover` | 封面图 |
| PUT | `/api/media/{id}` | 编辑元数据 |
| DELETE | `/api/media/{id}` | 删除(含文件) |

### 6.4 WebSocket
| 事件 | 说明 |
|------|------|
| `task:progress` | {task_id, progress, status, speed} |
| `task:completed` | {task_id, file_path} |
| `task:failed` | {task_id, error} |

---

## 7. 各平台解析策略

### 7.1 网易云音乐
- **方式**：第三方 API (NeteaseCloudMusicApi 自建或公共接口)
- **流程**：搜索/获取歌曲 ID → 解析音乐直链 → 下载
- **音质**：FLAC > 320kbps > 128kbps（逐级降级）
- **元数据**：Mutagen 写入 ID3 标签（标题/艺术家/专辑/封面）
- **歌单**：获取全部 song IDs → 批量创建任务

### 7.2 QQ 音乐
- **方式**：第三方 QQMusic API
- **流程**：获取歌曲 mid → 解析直链 → 下载
- **音质**：FLAC > 320kbps > 128kbps
- **元数据**：写入 ID3 标签
- **歌单**：解析歌单 ID → 获取歌曲列表

### 7.3 Spotify
- **方式**：spotDL + yt-dlp
- **流程**：Spotify API 获取元数据 → spotDL 匹配 YouTube 音频 → yt-dlp 下载 → FFmpeg 写入元数据
- **限制**：音质取决于 YouTube 源

### 7.4 抖音
- **引擎**：yt-dlp + 第三方解析 API
- **去水印**：获取无水印直链
- **动态照片**：检测视频时长 0~15s → 按视频下载 MP4（非静态封面）
- **批量**：作者主页/合集逐一解析

### 7.5 YouTube
- **引擎**：yt-dlp
- **音质**：视频 `bestvideo[height<=2160]+bestaudio/best`，音频 `bestaudio`
- **批量**：播放列表自动展开

### 7.6 Bilibili
- **引擎**：yt-dlp + bilibili-api
- **批量**：合集/系列解析

### 7.7 全网影视搜索
- **YouTube/Bilibili**：调用搜索 API，按标题匹配影视内容
- **BT 搜索**：集成多个 BT 搜索引擎 API → 聚合磁力链接
- **下载**：磁力链 → aria2；视频站 → yt-dlp

---

## 8. 前端页面

| 路由 | 页面 | 功能 |
|------|------|------|
| `/` | 仪表盘 | 统计 + 最近任务 + 快速操作 |
| `/download` | 下载中心 | URL 输入/搜索 + 格式选择 |
| `/download/batch` | 批量下载 | 歌单解析结果 + 勾选批量 |
| `/tasks` | 任务管理 | 下载队列 + 进度 + 操作 |
| `/library` | 媒体库 | 网格/列表 + 搜索 + 播放 |
| `/library/music` | 音乐库 | 按艺术家/专辑分类 |
| `/library/video` | 视频库 | 按平台分类 |
| `/player/:id` | 播放器 | 在线播放 |
| `/settings` | 设置 | 下载目录/并发数/平台配置 |

---

## 9. 项目目录结构

```
D:\Dowland\media-fetch\
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI 路由
│   │   │   ├── __init__.py
│   │   │   ├── downloads.py  # 下载相关
│   │   │   ├── media.py      # 媒体库
│   │   │   ├── search.py     # 搜索
│   │   │   ├── settings.py   # 设置
│   │   │   └── ws.py         # WebSocket
│   │   ├── core/             # 核心配置
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   └── dependencies.py
│   │   ├── models/           # SQLAlchemy 模型
│   │   │   ├── download_task.py
│   │   │   ├── media_item.py
│   │   │   └── platform_config.py
│   │   ├── services/         # 业务逻辑
│   │   │   ├── parser_factory.py  # 解析器工厂
│   │   │   ├── parsers/          # 各平台解析器
│   │   │   │   ├── base.py          # 抽象基类
│   │   │   │   ├── youtube.py
│   │   │   │   ├── bilibili.py
│   │   │   │   ├── douyin.py
│   │   │   │   ├── netease.py
│   │   │   │   ├── qqmusic.py
│   │   │   │   ├── spotify.py
│   │   │   │   └── torrent.py       # 磁力搜索
│   │   │   ├── downloader.py    # 下载管理
│   │   │   ├── media_manager.py # 媒体库管理
│   │   │   └── metadata.py      # 元数据写入
│   │   ├── tasks/             # Celery 任务
│   │   │   ├── __init__.py
│   │   │   └── download_tasks.py
│   │   └── main.py            # 入口
│   ├── requirements.txt
│   ├── Dockerfile
│   └── celery_worker.py
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── DownloadCenter.tsx
│   │   │   ├── BatchDownload.tsx
│   │   │   ├── TaskManager.tsx
│   │   │   ├── MediaLibrary.tsx
│   │   │   ├── Player.tsx
│   │   │   └── Settings.tsx
│   │   ├── components/
│   │   │   ├── URLInput.tsx
│   │   │   ├── FormatSelector.tsx
│   │   │   ├── ProgressCard.tsx
│   │   │   ├── MediaCard.tsx
│   │   │   └── PlaylistParser.tsx
│   │   ├── api/               # API 调用
│   │   ├── hooks/             # WebSocket hooks
│   │   └── types/             # TypeScript 类型
│   ├── Dockerfile
│   └── vite.config.ts
├── media/
│   ├── video/                 # 视频存储
│   ├── music/                 # 音乐存储
│   └── temp/                  # 临时下载
├── docker-compose.yml
├── docker-compose.prod.yml
└── README.md
```

---

## 10. 第一阶段详细任务分解

### 10.1 基础框架
- [ ] Python FastAPI 项目初始化 + Poetry 依赖
- [ ] SQLAlchemy 模型 + Alembic 迁移
- [ ] Redis + Celery 集成配置
- [ ] React + Vite + TypeScript + Ant Design 初始化
- [ ] Docker Compose 开发编排

### 10.2 音乐下载核心
- [ ] 解析器工厂 + 抽象基类 (`services/parser_factory.py`)
- [ ] 网易云搜索 + 链接下载解析器
- [ ] QQ 音乐搜索 + 链接下载解析器
- [ ] Spotify 搜索 + 播放列表解析器
- [ ] 音质选择 + 下载任务创建
- [ ] Celery 下载任务封装（yt-dlp）
- [ ] FFmpeg 后处理 + ID3 元数据写入
- [ ] WebSocket 进度推送

### 10.3 歌单批量下载
- [ ] 歌单链接解析（网易云/QQ/Spotify）
- [ ] 条目列表展示 + 勾选全选
- [ ] 批量创建下载任务（并发控制）

### 10.4 抖音下载
- [ ] 抖音无水印解析（yt-dlp + 备用 API）
- [ ] 动态照片识别（检测 duration > 0 的视频源）
- [ ] 主页/合集批量解析

### 10.5 前端基础页面
- [ ] 下载中心（URL输入 + 搜索 + 格式选择）
- [ ] 任务管理（进度列表 + 取消/重试）
- [ ] 批量下载页（勾选 + 操作）
- [ ] 媒体库（网格/列表视图）
- [ ] 设置页（平台配置）

---

## 11. 风险与注意事项

1. **法律合规**：本工具仅限个人使用，用户应遵守当地版权法律，不得用于商业用途或传播下载内容。
2. **平台反爬**：建议默认并发 ≤ 3，高频下载可能触发风控。
3. **接口失效**：第三方解析接口可能失效，架构设计采用解析器工厂模式，方便接口切换。
4. **yt-dlp 更新**：需保持最新版本，Docker 定期重建。
5. **存储空间**：视频文件较大，建议提供空间预警。
6. **DRM 保护**：部分平台内容受 DRM 保护，无法通过本工具下载。
