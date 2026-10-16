# DownloadKit 测试覆盖报告

> 生成时间：2026-10-16  
> 当前版本：v0.6.0  
> 测试总数：1151 passed / 7 skipped

---

## 一、测试覆盖概览

### 1.1 测试文件统计

| 类型 | 数量 | 说明 |
|------|------|------|
| 单元测试 | ~620+ | pytest 用例（含服务端测试、douyin CLI、dry-run/status P1 特性） |
| 离线 E2E | ~170+ | 起真实服务 + 替身（含 5 条完整链路） |
| EXE 冒烟 | 10 项 | 打包后接口验证 |
| **总计** | **~801 项** | — |

### 1.2 命令组覆盖情况

| 命令组 | CLI 测试 | E2E | 服务端测试 | 状态 |
|--------|---------|-----|-----------|------|
| `search` | ✅ 5 例 | ❌ | ❌ | 基本覆盖 |
| `download` | ✅ 3 例 | ❌ | ❌ | 基本覆盖 |
| `playlist` | ✅ 3 例 | ❌ | ❌ | 基本覆盖 |
| `douyin` | ✅ 21 例 | ✅ | ❌ | **覆盖良好** |
| `parse` | ✅ 43 例 | ✅ 30 例 | ❌ | 覆盖良好 |
| `video` | ✅ 43 例 | ✅ 30 例 | ❌ | 覆盖良好 |
| `queue` | ✅ 24 例 | ✅ 22 例 | ❌ | 覆盖良好 |
| `subscribe` | ✅ 101 例 | ✅ 106 例 | ❌ | 覆盖良好 |
| `files` | ✅ 60 例 | ✅ 49 例 | ❌ | 覆盖良好 |
| `sniff` | ✅ 55 例 | ✅ 56 例 | ❌ | 覆盖良好 |
| `bookmarks import` | ✅ 部分 | ✅ | ❌ | 部分覆盖 |
| `bookmarks probe` | ✅ 9 例 | ❌ | ✅ 10 例 | **覆盖良好** |
| `settings` | ✅ 65 例 | ✅ 67 例 | ❌ | 覆盖良好 |
| `collections` | ✅ 50 例 | ✅ 64 例 | ✅ 13 例 | **覆盖良好** |
| `history` | ✅ 29 例 | ✅ 29 例 | ✅ 15 例 | **覆盖良好** |

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
| `/api/history/*` | test_server_history.py | ✅ **新增** |
| `/api/collections/*` | test_server_collections.py | ✅ **新增** |
| `/api/bookmarks/probe/*` | test_server_bookmarks_probe.py | ✅ **新增** |

### 2.2 缺少服务端测试的端点

| 端点 | 数量 | 建议优先级 |
|------|------|-----------|
| `/api/cookies/*` | 3 个 | P1 |
| `/api/video/episodes` | 1 个 | P2 |
| `/api/debug/*` | 1 个 | P3 - 调试用 |

**合计：5 个端点缺少服务端单元测试**（原 18 个，本次补 13 个）

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
| `downloadkit/history.py` | test_cli_history.py + test_server_history.py | 下载历史 ✅ |
| `downloadkit/collection.py` | test_collection_refresh.py + test_server_collections.py | 收藏歌单 ✅ |

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

## 四、任务完成状态

### 4.1 P0 任务

#### 任务 1：补全服务端单元测试 ✅ 已完成 ✅ 已完成

新建三个服务端测试文件：
```
tests/test_server_history.py      # /api/history/* 5 个端点 → 15 用例
tests/test_server_collections.py  # /api/collections/* 6 个端点 → 13 用例
tests/test_server_bookmarks_probe.py  # /api/bookmarks/probe/* 3 个端点 → 15 用例
```

每个文件覆盖：
- 正常路径（200）
- 参数校验（400）
- 不存在资源（404）
- 路由顺序不冲突（防参数路由吃掉静态路由）
- 边界：空数据、重复、非法输入

**验收**：43 个新增用例全部通过，全量 1098 passed / 7 skipped，无回归。

#### 任务 2：补全 douyin CLI 测试 ✅ 已完成

新建 `tests/test_cli_douyin.py`（21 用例），覆盖：

- `parse_url`：有效 URL（完整/短链/分享文本）→ 提取正确；非法输入 → None
- CLI `douyin` 命令：
  - 无链接 → 打印中文提示，exit 0
  - fetch_content 抛 ValueError → 打印错误，exit 0
  - download_content 抛 ValueError → 打印下载失败，exit 0
  - 视频 / 图文 / 动图 三种内容类型的输出文案
  - `-o` 输出目录正确传给 download_content
  - 多图多文件时总大小和各文件明细
  - `--help` 列出所有选项

测试策略：monkeypatch `cli.fetch_content` / `cli.download_content` / `cli.parse_url`，
不启动服务，不连网络。

**验收**：21 个新增用例全部通过，全量 1119 passed / 7 skipped，无回归。

#### 任务 3：增加集成测试 ✅ 已完成

新建 `tests/test_e2e_full_flow.py`（22 用例），启真实 server 子进程（端口 8792），
用 httpx 走 HTTP 验证 5 条链路：

- 链路 1：书签导入 → 探测 → 结果查看（POST /api/bookmarks/import + POST/GET/POST probe）
- 链路 2：收藏歌单 CRUD（GET list / POST create / GET show / DELETE，不触发网络解析）
- 链路 3：下载历史 CRUD（CLEAR → COUNT → LIST → SEARCH → DELETE，含分页/参数校验）
- 链路 4：队列状态查看（GET /api/queue/status，空队列也 200）
- 链路 5：跨链路状态一致性（历史清空不影响收藏列表；探测不影响历史记录）

测试策略：module 级 fixture 启停 server，asyncio.run 发异步请求，
每条链路独立 class，端口与 test_server_entry.py（8791）不冲突。

**验收**：22 个新增用例全部通过，全量 1141 passed / 7 skipped，无回归。

---

### 4.2 P1 任务（建议完成）

#### 任务 4：添加 `--dry-run` 模式 ✅ 已完成

对以下命令添加 `--dry-run` 选项：
- `playlist` — 解析歌单后输出曲目列表，不触发下载
- `download` — 解析单曲后输出信息，不触发下载
- `collections add` — 本地解析歌单后预览信息，不 POST 入库
- `bookmarks probe` — 解析书签 HTML 后列出待探测 URL，不启动后端任务

测试策略：monkeypatch `cli.run_async` 直接返回值，绕过 asyncio 事件循环；
拦截 `_coll_api` / `_probe_api` 确认无网络调用。

**验收**：10 个新增用例全部通过，全量 1151 passed / 7 skipped，无回归。

#### 任务 5：添加 `downloadkit status` 命令 ✅ 已完成

新增 `status` 命令，展示：
- 服务连通性（ping `/api/settings/get`）
- 队列状态（pending/downloading/paused/completed/failed 计数）
- 订阅创作者数量
- 收藏歌单数量
- 历史总条数
- 当前代理模式（direct/system/manual）

支持 `--json` 输出（管道友好）。服务未运行时给出中文提示，exit 0。

**验收**：6 个新增用例全部通过（含无服务/有服务/JSON 模式），全量 1151 passed / 7 skipped，无回归。

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
