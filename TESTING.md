# DownloadKit 测试覆盖报告

> 生成时间：2026-10-16  
> 当前版本：v0.6.0  
> 测试总数：1056 passed / 6 skipped

---

## 一、测试覆盖概览

### 1.1 测试文件统计

| 类型 | 数量 | 说明 |
|------|------|------|
| 单元测试 | ~550+ | pytest 用例 |
| 离线 E2E | ~150+ | 起真实服务 + 替身 |
| EXE 冒烟 | 10 项 | 打包后接口验证 |
| **总计** | **~716 项** | — |

### 1.2 命令组覆盖情况

| 命令组 | CLI 测试 | E2E | 服务端测试 | 状态 |
|--------|---------|-----|-----------|------|
| `search` | ✅ 5 例 | ❌ | ❌ | 基本覆盖 |
| `download` | ✅ 3 例 | ❌ | ❌ | 基本覆盖 |
| `playlist` | ✅ 3 例 | ❌ | ❌ | 基本覆盖 |
| `douyin` | ❌ | ✅ | ❌ | **缺 CLI 测试** |
| `parse` | ✅ 43 例 | ✅ 30 例 | ❌ | 覆盖良好 |
| `video` | ✅ 43 例 | ✅ 30 例 | ❌ | 覆盖良好 |
| `queue` | ✅ 24 例 | ✅ 22 例 | ❌ | 覆盖良好 |
| `subscribe` | ✅ 101 例 | ✅ 106 例 | ❌ | 覆盖良好 |
| `files` | ✅ 60 例 | ✅ 49 例 | ❌ | 覆盖良好 |
| `sniff` | ✅ 55 例 | ✅ 56 例 | ❌ | 覆盖良好 |
| `bookmarks import` | ✅ 部分 | ✅ | ❌ | 部分覆盖 |
| `bookmarks probe` | ✅ 9 例 | ❌ | ❌ | **缺 E2E** |
| `settings` | ✅ 65 例 | ✅ 67 例 | ❌ | 覆盖良好 |
| `collections` | ✅ 50 例 | ✅ 64 例 | ❌ | **缺服务端测试** |
| `history` | ✅ 29 例 | ✅ 29 例 | ❌ | **缺服务端测试** |

---

## 二、服务端端点覆盖情况

### 2.1 已有测试覆盖的端点

| 端点 | 测试文件 | 覆盖情况 |
|------|---------|---------|
| `/api/search` | test_searcher.py | ✅ |
| `/api/download` | test_download_queue.py | ✅ |
| `/api/files/*` | test_files_e2e.py | ✅ |
| `/api/queue/*` | test_cli_queue.py | ✅ |
| `/api/subscriptions/*` | test_cli_subscribe.py | ✅ |
| `/api/settings/*` | test_cli_settings.py | ✅ |
| `/api/bookmarks/import` | test_cli_bookmarks.py | ✅ |
| `/api/sniff` | test_cli_sniff.py | ✅ |
| `/api/open-file` | test_open_file.py | ✅ |
| `/api/open-dir` | test-exe.ps1 | ✅ |

### 2.2 缺少服务端测试的端点

| 端点 | 数量 | 建议优先级 |
|------|------|-----------|
| `/api/history/*` | 5 个 | **P0** - P5-7b 新增 |
| `/api/collections/*` | 6 个 | **P0** - P5-7 新增 |
| `/api/bookmarks/probe/*` | 3 个 | **P0** - P5-9 新增 |
| `/api/cookies/*` | 3 个 | P1 |
| `/api/video/episodes` | 1 个 | P2 |
| `/api/debug/*` | 1 个 | P3 - 调试用 |

**合计：18 个端点缺少服务端单元测试**

---

## 三、模块覆盖情况

### 3.1 已有测试覆盖的模块

| 模块 | 测试文件 | 说明 |
|------|---------|------|
| `downloadkit/playlist.py` | test_playlist.py | 歌单解析 |
| `downloadkit/searcher.py` | test_searcher.py | 搜索聚合 |
| `downloadkit/downloader.py` | test_downloader.py | 下载引擎 |
| `downloadkit/video_service.py` | test_cli_video.py | 视频平台分发 |
| `downloadkit/douyin.py` | test_douyin_*.py (多个) | 抖音解析 |
| `downloadkit/bookmarks.py` | test_bookmarks.py | 书签解析 |
| `downloadkit/sniffer.py` | test_sniffer.py | 嗅探引擎 |
| `downloadkit/episodes.py` | test_episodes.py | 选集展开 |
| `downloadkit/history.py` | test_cli_history.py | 下载历史（缺服务端测试） |
| `downloadkit/collection.py` | test_collection_refresh.py | 收藏歌单（缺服务端测试） |

### 3.2 缺少测试的模块

| 模块 | 优先级 | 说明 |
|------|--------|------|
| `downloadkit/platforms/*.py` | P1 | 音乐平台适配器（netease/qqmusic/migu/gequbao/itzo） |
| `downloadkit/bilibili.py` | P2 | B站下载 |
| `downloadkit/youtube.py` | P2 | YouTube 下载 |
| `downloadkit/xiaohongshu.py` | P2 | 小红书下载 |
| `downloadkit/generic_video.py` | P2 | 通用视频解析 |
| `downloadkit/douyin_browser.py` | P1 | 抖音浏览器后端 |

---

## 四、建议的下个版本开发任务

### 4.1 P0 任务（必须完成）

#### 任务 1：补全服务端单元测试

创建以下测试文件：
```
tests/test_server_history.py      # /api/history/* 5 个端点
tests/test_server_collections.py  # /api/collections/* 6 个端点
tests/test_server_bookmarks_probe.py  # /api/bookmarks/probe/* 3 个端点
```

每个文件覆盖：
- 正常路径（200）
- 参数校验（400）
- 不存在资源（404）
- 并发安全（如果有状态）

#### 任务 2：补全 douyin CLI 测试

创建 `tests/test_cli_douyin.py`，覆盖：
- 参数校验（URL 格式、输出目录）
- 输出格式（JSON、表格）
- 异常处理（无链接、解析失败）

#### 任务 3：增加集成测试

创建 `tests/test_e2e_full_flow.py`，覆盖：
- 搜索 → 选曲 → 下载 → 队列查看
- 歌单导入 → 收藏 → 刷新
- 书签导入 → 探测 → 结果查看

---

### 4.2 P1 任务（建议完成）

#### 任务 4：添加 `--dry-run` 模式

对以下命令添加 `--dry-run` 选项：
- `download` - 显示会下载什么
- `playlist` - 显示歌单内容
- `collections add` - 显示会收藏什么
- `bookmarks probe` - 显示会探测哪些链接

#### 任务 5：添加 `downloadkit status` 命令

展示当前状态：
- 服务是否运行
- 队列状态（进行中/已完成/失败）
- 订阅状态
- 收藏歌单数量
- 历史记录数量
- 代理状态

#### 任务 6：统一退出码文档

在 PLAN.md 或新建 `CONTRIBUTING.md` 中明确：
- 探测器组（sniff/bookmarks/probe）→ exit 1
- 状态查询组（queue/subscribe/files/collections/history）→ exit 0
- 用法错误 → exit 2

---

### 4.3 P2 任务（可选）

#### 任务 7：CLI 自动补全

为 bash/zsh/fish/powershell 生成补全脚本。

#### 任务 8：添加性能基准测试

```
tests/benchmarks/test_download_speed.py
tests/benchmarks/test_search_latency.py
```

防止 P5-8 修的 yt-dlp 性能问题再次回归。

#### 任务 9：重构 `_run_async` 异常处理

避免 RuntimeError 被误吞的问题再次发生。

---

## 五、验收标准

每个任务完成后需满足：

1. **单元测试**：新增用例全部通过
2. **覆盖率**：相关模块覆盖率提升 ≥ 10%
3. **E2E**：关键路径有离线实测
4. **编码**：UTF-8 无损坏
5. **文档**：PLAN.md 同步更新

---

## 六、参考文件

- `PLAN.md` - 开发计划与进度
- `DEVELOPMENT.md` - 开发环境搭建
- `ARCHITECTURE.md` - 架构说明
- `CHANGELOG.md` - 更新日志
