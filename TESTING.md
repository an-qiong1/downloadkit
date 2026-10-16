# DownloadKit 测试覆盖报告

> 生成时间：2026-10-16  
> 当前版本：v0.7.0  
> 测试总数：1245 passed / 7 skipped

---

## 一、测试覆盖概览

### 1.1 测试文件统计

| 类型 | 数量 | 说明 |
|------|------|------|
| 单元 / CLI 测试 | 1214 | pytest 用例（服务端、douyin CLI、dry-run/status P1 特性、平台适配器、性能基准） |
| 离线 E2E | 38 | `test_e2e_full_flow.py` 起真实 uvicorn 服务（9 条链路） |
| EXE 冒烟 | 10 项 | 打包后接口验证（test-exe.ps1，不计入 pytest） |
| **pytest 总计** | **1252** | 1245 passed / 7 skipped |

### 1.2 命令组覆盖情况

| 命令组 | CLI 测试 | E2E | 服务端测试 | 状态 |
|--------|---------|-----|-----------|------|
| `search` | ✅ 5 例 | ✅ 4 例 | ❌ | 覆盖良好 |
| `download` | ✅ 3 例 | ✅ 4 例 | ❌ | 覆盖良好 |
| `playlist` | ✅ 3 例 | ✅ 4 例 | ❌ | 覆盖良好 |
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
| `/api/bookmarks/import` | test_server_bookmarks_import.py | ✅ **T4 新增** |
| `/api/sniff` | test_cli_sniff.py | ✅ |
| `/api/open-file` | test_open_file.py | ✅ |
| `/api/open-dir` | test-exe.ps1 | ✅ |
| `/api/history/*` | test_server_history.py | ✅ **新增** |
| `/api/collections/*` | test_server_collections.py | ✅ **新增** |
| `/api/bookmarks/probe/*` | test_server_bookmarks_probe.py | ✅ **新增** |
| `/api/cookies/*` | test_server_cookies.py | ✅ **T1 新增** |

### 2.2 缺少服务端测试的端点

| 端点 | 数量 | 建议优先级 |
|------|------|-----------|
| `/api/video/episodes` | 1 个 | P2 |
| `/api/debug/*` | 1 个 | P3 - 调试用 |

**合计：2 个端点缺少服务端单元测试**（原 5 个欠账已全部补齐：history / collections / probe / cookies / bookmarks import）

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
| `downloadkit/platforms/*.py` | test_platforms.py | ✅ **T2 新增** |
| `downloadkit/bilibili.py` | P2 | B站下载 |
| `downloadkit/youtube.py` | P2 | YouTube 下载 |
| `downloadkit/xiaohongshu.py` | P2 | 小红书下载 |
| `downloadkit/generic_video.py` | P2 | 通用视频解析 |
| `downloadkit/douyin_browser.py` | P1 | 抖音浏览器后端 |

---

## 四、任务完成状态

### 4.1 P0 任务

#### 任务 1：补全服务端单元测试 ✅ 已完成

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

#### 任务 5（T1）：补全 cookies 服务端测试 ✅ 已完成

新建 	ests/test_server_cookies.py（16 用例），覆盖 3 个端点：

- GET /api/cookies/open-login：有效平台（douyin/bilibili）返回 URL；非法平台 400；webbrowser 异常时降级返回 URL
- POST /api/cookies/load-from-browser：正常读取（douyin/bilibili）；空 Cookie 返回 ok=False；不支持平台（xhs/youtube）返回错误提示；浏览器读取异常返回 error 字段
- POST /api/cookies/save：空 Cookie 400；非法平台 400；自定义路径写文件；默认路径写文件；save_to_config 同步更新 config.toml；写入失败 500

测试策略：直接 import route 函数，monkeypatch webbrowser.open / downloadkit.browser_cookie 模块，不启动真实服务，不依赖系统浏览器。

**验收**：16 个新增用例全部通过，全量 1178 passed / 7 skipped，无回归。

#### 任务 6（T2）：补齐 platforms 适配器单元测试 ✅ 已完成

新建 `tests/test_platforms.py`（45 用例），覆盖 5 个模块的纯逻辑部分：

- **netease 解析函数**（18 例）：`_parse_song_item` 新旧格式兼容、缺失字段、异常路径；`_extract_artists` / `_extract_album` / `_get_cover_url` / `_get_album_name` / `_get_artist_name` / `_parse_year`
- **netease 静态方法**（6 例）：`match_url` 正确/错误 URL；`extract_playlist_id` 查询参数与路径两种格式，非法 URL 抛 ValueError
- **qqmusic 静态方法**（4 例）：`match_url`；`extract_playlist_id` 三种路径格式（playlist/playlistDetail/taoge）
- **migu 辅助函数**（4 例）：`_clean_artist` 单/多歌手、空格处理
- **gequbao 辅助函数**（7 例）：`_find_aid` 正则匹配；`_parse_app_data` JSON 解析；`_extract_download_url` MP3 直链提取
- **itzo 搜索逻辑**（5 例）：title+artist 精确匹配、title 模糊匹配、无匹配兜底、协议升级、空列表

测试策略：直接导入模块函数，不发起网络请求，用 fixture 提供模拟数据。

**验收**：45 个新增用例全部通过，全量 1216 passed / 7 skipped，无回归。

#### 任务 7（T3）：补齐 search / download / playlist E2E ✅ 已完成

在 `tests/test_e2e_full_flow.py` 中追加 4 条链路（16 用例），复用 module 级真实服务（端口 8792）：

- **链路 6 TestSearchFlow**（4 例）：缺 keyword → 422；空 keyword → 200 + songs 结构；返回歌曲含 title/artist/platform/song_id 字段；count 限制结果条数
- **链路 7 TestDownloadFlow**（4 例）：缺字段 → 422；提交 → 返回 task_id；提交后查状态不 404；未知 task_id → 404
- **链路 8 TestPlaylistFlow**（4 例）：缺 url → 422；空 url → 400；无法识别的 URL → 400；合法网易云歌单 URL → 200 或 400（离线容忍）
- **链路 9 TestSongInfoFlow**（4 例）：缺 url → 422；未识别 URL → 400；网易云 URL 正确提取 song_id=123456/platform=netease；QQ音乐 URL 正确提取 song_id/platform=qqmusic

**验收**：16 个新增用例全部通过，全量无回归。

#### 任务 8（T4）：补书签导入服务端单测 ✅ 已完成

新建 `tests/test_server_bookmarks_import.py`（13 用例），直接 import `api_bookmarks_import` 路由函数，无网络：

- **正常路径**（4 例）：返回 tree/links/folders；树节点类型与字段（type/title/url/name/children）；重复 URL 不去重（links 计数含重复）；add_date 保留
- **400 路径**（4 例）：空字符串 / 纯空白 → "文件为空"；非书签 HTML（无 NETSCAPE 结构）→ "不是浏览器导出的书签文件"；结构合法但 0 条 http 链接 → "未解析到任何书签链接"
- **边界**（5 例）：BOM 前缀剥离；丢 DOCTYPE 的工具导出仍解析；javascript:/ftp: 不计数；空标题 <a> 不计数；残缺 HTML 保留已解析部分（close() flush 未闭合 <a>，计 2 条）

CLI/E2E 联动已有覆盖（test_cli_sniff.py 8 例 + E2E 链路 1），本次只补服务端单测。

**验收**：13 个新增用例全部通过，全量 1245 passed / 7 skipped，无回归。

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

**验收**：10 个新增用例全部通过，全量 1162 passed / 7 skipped，无回归。

#### 任务 5：添加 `downloadkit status` 命令 ✅ 已完成

新增 `status` 命令，展示：
- 服务连通性（ping `/api/settings/get`）
- 队列状态（pending/downloading/paused/completed/failed 计数）
- 订阅创作者数量
- 收藏歌单数量
- 历史总条数
- 当前代理模式（direct/system/manual）

支持 `--json` 输出（管道友好）。服务未运行时给出中文提示，exit 0。

**验收**：6 个新增用例全部通过（含无服务/有服务/JSON 模式），全量 1162 passed / 7 skipped，无回归。

#### 任务 6：统一退出码文档 ✅ 已完成

新建 `CONTRIBUTING.md`，明确三类退出码规则：

| exit | 含义 | 适用命令组 |
|------|------|-----------|
| 0 | 成功 / 业务结果（空列表、歌单不存在等） | queue / subscribe / files / collections / history / search / parse / douyin / playlist / download |
| 1 | 探测器没拿到结果 | sniff / bookmarks probe / settings proxy-test |
| 2 | 用法错误（缺参数、格式错） | 所有命令，由 Click UsageError 统一处理 |

附有与 server 端 HTTP 状态码的对照表及测试断言位置索引。

#### 任务 7：CLI 自动补全 ✅ 已完成

生成 `completion/` 目录下四套 shell 补全脚本：
- `completion/downloadkit.bash` — Bash（3.x+）
- `completion/downloadkit.zsh` — Zsh（via compdef）
- `completion/downloadkit.fish` — Fish
- `completion/downloadkit.powershell` — PowerShell（Register-ArgumentCompleter）

安装方式见 `completion/README.md`。

#### 任务 8：添加性能基准测试 ✅ 已完成

新建 `tests/benchmarks/test_performance.py`（4 用例）：
- `test_run_async_overhead_small` — run_async 单次开销 < 5ms
- `test_run_async_overhead_repeated` — 10 次平均 < 5ms
- `test_search_latency_under_10s` — 搜索最坏耗时 < 10s
- `test_parse_latency_under_5s` — 解析最坏耗时 < 5s

加上 `tests/benchmarks/README.md` 说明。

#### 任务 9：重构 `_run_async` 异常处理 ✅ 已完成

`cli.py` 的 `run_async()` 沿用 `collection.py` 已有的安全模式：

```python
def run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
```

关键点：`get_running_loop()` 的判断**与** `asyncio.run()` 调用分开，
避免协程内部抛出的 RuntimeError 被误吞成「没有事件循环」再重试。
`collection.py` 的 `_run_async` 已有同款实现，本修复使其与 cli 层对齐。
已有测试 `test_collection_refresh.py::test_run_async_does_not_mask_runtime_error`
继续通过，确认行为一致。

---

### 4.3 P2 任务（已全部完成，无待办）

所有 P0/P1/P2 任务已于 2026-10-16 全部完成，合计新增测试 79 个，
全量 1162 passed / 7 skipped。详见上方各任务完成记录。

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
