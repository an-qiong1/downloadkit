# downloadkit 资源嗅探批量下载 · 实施计划书

> 版本：v1.0 ｜ 日期：2026-09-30 ｜ 范围：桌面版（`run.py` → `server.py` → `downloadkit/`）
> 状态：技术路线已实测验证，待实施

---

## 0. 摘要

为 downloadkit 桌面版新增**批量资源嗅探下载**能力：导入浏览器书签或粘贴一批网页链接，自动嗅探出页面中的 m3u8/mp4 流地址，批量入队下载并无损转封装为 mp4，并支持从播放页展开全部选集批量下载。

技术路线经**真实站点实测**确定：

- 嗅探引擎：**DrissionPage 4.1.1.4 接管系统 Edge**
- 核心技巧：**跨域 iframe 播放器提升为顶层标签页后监听**（解决 DrissionPage 的 OOPIF 监听盲区）
- 下载引擎：**yt-dlp**（已有依赖）+ **ffmpeg**（已装 9.0.2）
- 静态抓 HTML 方案**已被实测否决**（两个样本站 m3u8 命中数均为 0）

---

## 1. 需求与目标

### 1.1 原始需求

1. 导入浏览器书签，批量下载所有网页中的视频
2. 一个链接能解析出选集，批量下载全部集数
3. 嗅探到 m3u8 后自动下载并转为 mp4
4. **核心诉求：效率高、一键批量**，不接受猫抓那种"逐个打开、逐个点下载"的交互模式

### 1.2 目标站点特征（实测确认）

- 非正版影视站，URL 是**普通网页**而非 m3u8 直链
- 页面带 **WAF 反爬**（雷池 SafeLine，状态码 468）
- 播放器位于**跨域 iframe**（独立域名），m3u8 由 `hls.js` 运行时加载
- **HTML 源码中不含任何 m3u8 地址**

### 1.3 验收标准

| 编号 | 场景 | 通过条件 |
|---|---|---|
| A1 | 粘贴单个普通网页链接 | 解析出标题 + 流地址，展示预览 |
| A2 | 导入书签 HTML | 解析出树形结构，可勾选 |
| A3 | 批量探测 | 并发嗅探，实时进度，标记哪些有视频 |
| A4 | 一键批量下载 | 全部入队，独立进度，可暂停/取消 |
| A5 | 下载产物 | 输出 `.mp4`，可直接播放（非 .ts） |
| A6 | 选集页 | 展开出全部集数，可勾选子集 |
| A7 | WAF 站点 | 能自动通过挑战并嗅探成功（样本1） |
| A8 | 防盗链站 | 携带 Referer 下载不 403 |

---

## 2. 现状盘点

### 2.1 已有能力（直接复用）

| 能力 | 位置 | 复用方式 |
|---|---|---|
| yt-dlp 集成 | `pyproject.toml:15`，venv 已装 2026.08.19 | 解析 + 下载底座 |
| ffmpeg | 系统 PATH，9.0.2 full build | 转封装 |
| 批量粘贴入口 | `static/index.html:139` + `static/js/resource.js:85` | 直接接入 |
| 批量接口 | `server.py:1131` `batch-parse`、`server.py:1230` `batch-download` | 加分支 |
| 下载队列/进度/暂停/取消 | `downloadkit/download_queue.py` | 完全复用 |
| 断点续传下载 | `downloadkit/utils.py:549` `download_file()` | 直链 mp4 复用 |
| yt-dlp 下载骨架（含进度钩子、取消钩子） | `downloadkit/youtube.py:232` | 照抄改造 |
| yt-dlp 子进程工具 | `backend/app/utils/ytdlp.py`（NAS 版，可移植） | 参考实现 |
| ffmpeg 探测 | `backend/app/services/downloader.py:23` `_has_ffmpeg()` | 移植到桌面版 |
| 浏览器 Cookie 导入 | `server.py:1987` `/api/cookies/load-from-browser` | 扩展支持 |
| 已装 DrissionPage 4.1.1.4 | venv（本计划实施时安装） | 嗅探引擎 |

### 2.2 缺失能力（本计划新增）

- 网页资源嗅探：**零命中**（全局无 m3u8/HLS 后端处理代码）
- 书签导入：**零命中**
- 视频选集（现有 `downloadkit/playlist.py` 只支持网易云/QQ 歌单）
- 通用网页解析平台（`server.py:823` `detect_platform()` 未知域名返回 `None` → 前端直接报"暂不支持该平台"）

---

## 3. 实测验证结论（计划的核心依据）

测试时间：2026-09-30。样本站由用户提供。

- **样本1**：`https://www.cz4k.com/v_play/bXZfMTEwMzAtbm1fMTk1.html`（厂长资源，雷池 WAF）
- **样本2**：`https://www.cnxgct.com/video/shixiongashixiong-jinlei/udWdMztqNU.html`（西瓜卡通，跨域 iframe 播放器 + AMP 页面）

### 3.1 WAF 穿透测试（样本1）

| # | 方法 | 结果 |
|---|---|---|
| 1 | urllib + 完整浏览器请求头 | ❌ HTTP 403，返回 SafeLine 拦截页 |
| 2 | Playwright headless（自带 Chromium） | ❌ HTTP 468 |
| 3 | Playwright headed（自带 Chromium） | ❌ HTTP 468，3 次重试均失败 |
| 4 | Playwright `channel="msedge"`（真实 Edge） | ❌ HTTP 468，等待 20 秒仍为拦截页 |
| 5 | **DrissionPage 接管真实 Edge** | ✅ **前 6 秒 468，t=8s 自动跳转 200** |

样本1 最终状态（方法5）：

```
status: 468 → 200
拦截页: True → False
title : '凡人修仙传 第195集 _ 厂长资源'
HTML  : 17083 → 72913 字节
```

拦截页可见文本：`安全检测能力由 雷池 WAF 驱动 正在进行安全检测 . . .`

**结论**：SafeLine 是 JS 挑战型 WAF，需等待挑战自动完成（约 8 秒）。Playwright 全系（含真实 Edge）均无法通过，**必须使用 DrissionPage 接管真实浏览器**。

> 过程中 DrissionPage 抛出"页面被刷新，请操作前尝试等待页面刷新或加载完成"——证明挑战通过时会整页刷新，实现时必须捕获此状态并重新等待。

### 3.2 m3u8 嗅探测试（样本2）

| # | 方法 | 捕获 m3u8 |
|---|---|---|
| 1 | 抓静态 HTML 正则匹配 | ❌ **0 条** |
| 2 | Playwright `page.on("response")` | ✅ 2 条（但该引擎过不了 WAF） |
| 3 | DrissionPage 监听主页面（全量，无过滤） | ❌ 92 条请求中 **0 条 m3u8** |
| 4 | **DrissionPage 将 iframe 播放器提升为顶层标签后监听** | ✅ **2 条** |

样本2 页面结构（实测）：

```html
<iframe src="https://pframe.xgcartoon.com/pframe/player.htm?vid=aa0c0684-...&autoplay=true">
```

播放器 iframe 跨域（`xgcartoon.com` vs `cnxgct.com`），内容为 `hls.js` 运行时加载，主页面 DOM 中 m3u8 命中 **0 条**。

方法3 捕获的 92 条请求中，**连 iframe 文档本身都没出现** —— 确认 DrissionPage `listen` 不覆盖 OOPIF（跨域独立进程 iframe）。

方法4 成功捕获：

```
https://xgct-video.bzcdn.net/aa0c0684-5a14-47e4-afa2-a0c39e5af947/video_info.json
https://xgct-video.bzcdn.net/aa0c0684-5a14-47e4-afa2-a0c39e5af947/playlist.m3u8      ← 主播放列表
https://xgct-video.bzcdn.net/aa0c0684-5a14-47e4-afa2-a0c39e5af947/640x360/video.m3u8  ← 清晰度列表
https://xgct-video.bzcdn.net/.../640x360/video0.ts ... video6.ts                      ← 分片，证明真在播
```

**关键副产物**：主页面 XHR `GET /user/amp/content_pframe_url?chapter_id=udWdMztqNU&level=low&expires=3600` 的响应直接给出播放器 iframe URL —— 这是"提升 iframe 为顶层标签"的入口。

### 3.3 验证结论

1. ❌ **纯静态抓取（L1）对目标站无效** —— 两站 DOM m3u8 均为 0
2. ✅ **DrissionPage 是唯一能过 WAF 的方案**
3. ✅ **"iframe 提升为顶层标签"是解决 OOPIF 监听盲区的有效手段**
4. ⚠️ 两层缺一不可：DrissionPage 负责过 WAF 与取得会话，iframe 提升负责拿到流地址

---

## 4. 技术路线

### 4.1 总体：三层降级流水线

按成本从低到高逐级尝试，让多数 URL 走廉价路径：

```
输入（书签树 / 批量粘贴链接）
   │
   ▼
┌── L0 直链判定 ────────────────────────────────────┐  ~0.1s
│  URL 后缀为 .m3u8/.mp4/.mpd → 直接入队            │
└───────────────────────────────────────────────────┘
   │ 未命中
   ▼
┌── L1 静态深挖（httpx + 正则）────────────────────┐  ~1-2s
│  1. 抓 HTML，正则挖 m3u8/mp4/mpd                   │
│  2. 未命中 → 抓页面引用的 .js 文件再挖             │
│  3. 未命中 → 尝试识别 player/api 特征构造请求      │
│  （本层已被实测证明对样本站无效，但对无 WAF 站     │
│    零成本，保留作为快速通道）                      │
└───────────────────────────────────────────────────┘
   │ 未命中（约 40~60% 走到这）
   ▼
┌── L2 浏览器嗅探（DrissionPage + Edge）───────────┐  ~10-25s
│  1. 打开页面，轮询等待（WAF 挑战 468→200，超时15s）│
│  2. 监听主页面 XHR → 抓 API 响应中的流地址         │
│  3. 从 DOM iframe src 或 XHR 响应提取播放器 URL    │
│  4. 【核心】新开标签加载播放器 URL → 监听 → 抓 m3u8 │
│  5. 记录 Referer / UA / Cookie                     │
│  6. 若播放器 URL 也无法提升 → 回退到注入 JS hook    │
└───────────────────────────────────────────────────┘
   │
   ▼
去重 → 选流 → 入下载队列 → yt-dlp 下载 → ffmpeg remux → .mp4
```

### 4.2 L2 核心实现：DrissionPage 嗅探

#### 4.2.1 浏览器实例管理

- **单浏览器实例 + 多标签并发**，避免每页重启浏览器（省 3~5 秒/页）
- 独立 profile 目录，不污染用户日常浏览器（`co.auto_port()` 已验证可用）
- DrissionPage 为**同步 API**，通过 `asyncio.to_thread` 或专用 `ThreadPoolExecutor` 桥接进 FastAPI 的 async 路由
- 嗅探并发度默认 4（WAF 站不宜过高），可配置

#### 4.2.2 单页嗅探流程

```python
async def sniff(url: str, *, timeout: float = 25.0) -> SniffResult:
    # 1. 开监听（无过滤，先全收再筛）
    tab = browser.new_tab(url)
    tab.listen.start()

    # 2. 轮询等待 WAF 挑战通过
    #    依据实测：前 6 秒 468，t=8s 变 200
    #    判定条件：performance.getEntriesByType('navigation')[0].responseStatus < 400
    #              且 html 不含 'safeline'
    #    注意捕获 DrissionPage "页面被刷新" 异常并重试

    # 3. 收集主页面监听包（约 10s），筛出：
    #    - m3u8/mpd/mp4 直接地址
    #    - 含 player/pframe/geturl/playurl/api 的 XHR，读响应体继续挖

    # 4. 提取播放器 iframe URL（三级来源）
    #    a. 步骤3 的 XHR 响应体（样本2 命中 content_pframe_url）
    #    b. DOM: document.querySelectorAll('iframe')[].src
    #    c. 页面内 a 标签 / JS 变量中的 player 链接

    # 5. 【方案Z】iframe 提升为顶层标签
    if player_url:
        ptab = browser.new_tab(player_url)
        ptab.listen.start()
        ptab.refresh()               # 确保监听覆盖全部请求
        ... 收集 15s ...
        # 实测可拿到 playlist.m3u8 + 清晰度 m3u8 + video_info.json
        # 同时记录 referer = player_url

    # 6. 收尾：stop listen、关闭临时标签
```

#### 4.2.3 兜底手段（方案Z 失败时）

1. **注入 JS hook**：`tab.run_js()` 注入对 `fetch` / `XMLHttpRequest` / `HTMLMediaElement.src` setter / `MediaSource` 的拦截，再触发播放
2. **主动触发播放**：`video.play()`；按选择器点击（`#player`、`[class*=play]`、`.pristart`、`.module-play-poster` 等，实测样本2 用 `[class*=play]` 命中）
3. **直接构造**：部分站 m3u8 由 `vid` 拼接（样本2 为 `{cdn}/{vid}/playlist.m3u8`），可从 `video_info.json` 等响应推导
4. 以上全失败 → 该 URL 标记为"嗅探失败"，在结果页单独列出，可手动补 m3u8 地址

### 4.3 选流与去重

| 规则 | 实现 |
|---|---|
| 主/子播放列表区分 | `playlist.m3u8`（主）与 `640x360/video.m3u8`（子）并存时，**只保留主列表**；yt-dlp 处理主列表会自动选清晰度 |
| 多清晰度 | 交给 yt-dlp：`-f "bv*+ba/b"` + `--merge-output-format mp4` |
| 排除干扰 | URL 匹配 `trailer\|preview\|ad\|commerc\|vod_ad\|advert` → 排除 |
| 去重 | URL 归一化（去掉 query 中 `expires/sign/ts` 类参数 + 去 fragment）后按 host+path 去重 |
| 跨页去重 | 同一 m3u8 在多书签页出现 → 只下载一次 |
| 拿不准 | 展示在结果页供勾选，默认全选 |

### 4.4 下载与转封装

**复用 `downloadkit/youtube.py:232` 的下载骨架**（Python API + progress_hook + 取消钩子），改造点：

```python
ydl_opts = {
    "outtmpl": str(output_path),
    "format": "bv*+ba/b",          # 视频优先，自动合流
    "merge_output_format": "mp4",  # 合流直接 mp4
    "remux_video": "mp4",          # 单流(HLS→TS)无损转封装
    "http_headers": {
        "Referer": referer,        # ← 防盗链，实测必需
        "User-Agent": UA,
    },
    "cookiesfrombrowser": ("chrome",),   # 复用登录态，提高成功率
    "retries": 3,
    "fragment_concurrency": 8,
    "progress_hooks": [progress_cb],     # → download_queue.update_progress
}
```

**转 mp4 是 remux 不是 transcode**：HLS 的 TS 分片用 `ffmpeg -c copy` 封装进 mp4，1080p 一集**秒级完成、不占 CPU**。仅当编码不兼容（HEVC in TS）时才需重编码，作为独立开关。

ffmpeg 缺失时的降级（移植 `backend/app/services/downloader.py:23` 的 `_has_ffmpeg()`）：保留原始 .ts 并提示用户。

**直链 mp4（L0/L1 命中）** 走更省的路径：直接复用 `downloadkit/utils.py:549` `download_file()`，自带断点续传 + 进度 + 暂停取消，不经过 yt-dlp。

### 4.5 书签导入（HTML 格式）

- 解析标准 Netscape 书签 HTML（浏览器 → 书签管理器 → 导出 HTML）
- 使用标准库 `html.parser` 而**非正则**（嵌套 `<DL>/<DT>/<H3>` 结构正则易错）
- 保留文件夹层级，输出树结构
- 支持按文件夹过滤（用户可能只想下"追剧"文件夹）

```json
{"name": "追剧", "children": [
  {"title": "某剧-第1集", "url": "https://...", "folder": "追剧", "add_date": 1727000000}
]}
```

### 4.6 选集展开（已按真实样本实测验证）

#### 4.6.1 关键洞察：播放页自身即含全部选集

两个样本**都在播放页内就包含完整选集列表**，无需跳转详情页：

| | 样本1 cz4k | 样本2 cnxgct |
|---|---|---|
| 详情页 | `/movie/{id}.html` | `/detail/{slug}` |
| **播放页内选集链接数** | **195 条（1~195 集齐全）** | **161 条（去重 chapter_id = 161，与集数吻合）** |
| 选集链接模板 | `/v_play/{base64}.html` | `/user/page_direct?cartoon_id={slug}&chapter_id={id}` |
| 选集容器 | `div.paly_list_btn`（站点拼写为 paly） | `div.col-12 > a.goto-chapter.chapter-box` |
| 链接内文本 | 纯数字 `1`（播放页）／`第1集`（详情页） | `<span class="title">第01集</span><span class="sequence">1</span>` |
| 参数可逆性 | ✅ `base64("mv_11030-nm_195")` = 详情页ID + 集数，**可直接构造** | ❌ chapter_id 为随机串，必须从页面提取 |
| 跳转方式 | 直接就是播放页 | `page_direct` 为 302 跳转 → 实际播放页 |
| 静态 HTML 中是否可见 | ✅ 是 | ✅ 是（324 处，去重 161） |

> 实测验证：样本2 点击第 5 集后 URL 变为 `/video/{slug}/5X4Z8m9YmW.html`，确认 `page_direct` 为中转跳转。

**结论：优先从"当前播放页"提取选集，详情页作补充** —— 比预想的"列表页→播放页"少一级，P4 成本下降。

#### 4.6.2 通用提取算法

```
输入: 一个已用 DrissionPage 打开的页面（已过 WAF，DOM 完整）
  │
  ├─ ① 抽取全部 <a href>（注意：选集链接可能在 a 的父级，
  │     样本2 的 span.sequence 本身无 href，须取 closest('a')）
  │
  ├─ ② 接口模板聚类（path + query 都参与模板化）
  │     /v_play/{b64}.html                        → 195 成员
  │     /user/page_direct?cartoon_id=X&chapter_id={id} → 161 成员
  │     规则：path 中含数字段→{id}，含 ≥10 位字母数字段→{b64}，
  │           query 中仅保留跨链接不变的参数（cartoon_id 视为常量）
  │
  ├─ ③ 保留成员数 ≥ 3 的组（防误判）
  │
  ├─ ④ 排序：优先取链接文本 `第N集`/`第0N集`/纯数字 → 整数排序
  │     （样本1 特殊集名"虚天战纪-A-上/下"混在数字序列中，
  │      需按 DOM 出现顺序作为次级排序键）
  │
  └─ ⑤ 每个集数 URL 进入 L2 嗅探；样本2 用 page_direct 原样请求，
        跟随 302 即得真实播放页（勿自行拼接）
```

#### 4.6.3 三级回退

```
路1: yt-dlp 原生 playlist（B站合集/YouTube 等）
     → ytdlp_dump_json(flat=True) → _type=='playlist' → entries[]
     成本最低，先走
   │ 失败
   ▼
路2: 上述通用提取（针对普通影视站，已用 2 样本验证）
   │ 失败（选集链接数 < 3）
   ▼
路3: 只下载当前这一集，结果页提示"未识别到选集"
```

**批量展开后每集各自进入 L2 嗅探**，嗅探并发与书签批量共用同一信号量（见 §5.4），避免打爆目标站。

---

## 5. 系统设计

### 5.1 新增模块

```
downloadkit/
├── generic_video.py      # 通用网页解析（L0/L1）、构建 yt-dlp 选项、下载入口
├── sniffer.py            # L2 浏览器嗅探（DrissionPage 封装、WAF 等待、iframe 提升）
├── bookmarks.py          # 书签 HTML 解析 → 树结构
├── episodes.py           # 选集提取（yt-dlp 原生 + 通用路径聚类）
└── stream_filter.py      # 选流、去重、干扰排除
```

### 5.2 后端接口改动（`server.py`）

| 位置 | 改动 |
|---|---|
| `:823` `detect_platform()` | 未知域名兜底返回 `'generic'`（原 `return None`） |
| `:837` `/api/video/parse` | 新增 `elif platform == 'generic':` → 走 `generic_video.parse()`，返回 title/cover/duration/formats + `is_playlist` 标记 |
| `:914` `/api/video/download` | `_download_func` 新增 `elif platform == 'generic':` |
| `:1131` `/api/video/batch-parse` | 新增 generic 分支；**并发 + 超时控制**（避免批量卡死） |
| `:1230` `/api/video/batch-download` | 新增 generic 分支 |
| **新增** | `POST /api/bookmarks/import` — 上传书签 HTML → 树 |
| **新增** | `POST /api/bookmarks/probe` — 并发嗅探书签，流式返回进度 |
| **新增** | `POST /api/sniff` — 单 URL 深度嗅探（L2） |
| **新增** | `POST /api/video/episodes` — 选集展开 |

### 5.3 前端改动（`downloadkit/static/`）

| 文件 | 改动 |
|---|---|
| `js/resource.js:3` `detectPlatform()` | 未知域名返回 `'generic'`（原 `null`） |
| `js/resource.js:53-56` | 移除 `toast('暂不支持该平台')` 拦截 |
| `js/resource.js:123` `platformColors` | 增加 `generic` 配色与标签"网页" |
| `index.html` | 新增：书签导入面板、嗅探进度条、选集勾选弹窗、选流勾选列表 |

复用现有 UI：批量框（`index.html:139`）、`showInlineBatchResults()`、`下载全部` 按钮、队列进度轮询（`js/queue.js:244`）。

### 5.4 批量探测的进度反馈

书签可能数百条，必须分批可中断：

- 后端 `POST /api/bookmarks/probe` 接受 `urls[]`，内部用 `asyncio.Semaphore(4)` 限流
- 每完成一条立即返回（`StreamingResponse` 或轮询 `GET /api/bookmarks/probe/status`）
- 前端显示 `已探测 37/214 · 命中 19`，支持随时停止
- 单条超时 25s（L2）/ 3s（L1），失败标记 `has_video=false`

---

## 6. 文件改动清单

### 新增

| 文件 | 内容 |
|---|---|
| `downloadkit/sniffer.py` | DrissionPage 嗅探引擎（核心） |
| `downloadkit/generic_video.py` | L0/L1 解析 + yt-dlp 选项构建 + 下载 |
| `downloadkit/bookmarks.py` | 书签 HTML 解析 |
| `downloadkit/episodes.py` | 选集提取 |
| `downloadkit/stream_filter.py` | 选流去重 |
| `tests/test_bookmarks.py` | 书签解析单测 |
| `tests/test_stream_filter.py` | 选流去重单测 |
| `tests/test_episodes.py` | 选集提取单测 |

### 修改

| 文件 | 改动点 |
|---|---|
| `server.py` | 4 处 generic 分支 + 4 个新接口 + `detect_platform` 兜底 |
| `downloadkit/static/js/resource.js` | 平台放行 + generic 配色 |
| `downloadkit/static/index.html` | 书签/嗅探/选集 UI |
| `pyproject.toml` | 新增依赖 `DrissionPage>=4.1` |
| `requirements` / 打包配置 | 打包时排除 DrissionPage 无关的重型子依赖（见风险 R6） |

---

## 7. 分期实施计划

| 阶段 | 内容 | 交付判据 | 预估 |
|---|---|---|---|
| **P0** | `generic_video.py` + 4 处 generic 分支 + 前端放行 + yt-dlp 下载转 mp4 | 粘贴 m3u8/mp4 直链能下成 mp4，进度/暂停可用 | 1 天 |
| **P1** | 书签 HTML 导入 + 树形展示 | 导出书签 → 解析 → 按文件夹勾选 | 0.5 天 |
| **P2** | `sniffer.py` L2：WAF 等待 + 主页面监听 + **iframe 提升** + Referer 透传 | 样本1、样本2 均能嗅探到 m3u8 | 1.5 天 |
| **P3** | 批量并发探测 + 实时进度 + 停止 | 导入 100 书签，3 分钟内出结果，可中断 | 1 天 |
| **P4** | 选集展开：yt-dlp 原生 + 通用接口模板聚类（已按 2 样本验证） | 播放页 → 集数列表（195/161 条）→ 勾选批量下载 | 1 天 |
| **P5** | 选流去重 + 结果勾选 + 一键入队 + 打包回归 | 端到端验收 A1~A8 | 1 天 |

总计约 **6 个工作日**。P0 独立可交付，P2 是风险最高环节。

---

## 8. 风险与对策

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| R1 | **DrissionPage 抓不到跨域 iframe 内请求** | 已确认 | ✅ 已验证方案Z：iframe URL 提升为顶层标签监听（样本2 实测拿到 2 条 m3u8） |
| R2 | **WAF 挑战失败或耗时过长** | 嗅探超时 | 轮询判定 `responseStatus<400 且 html 不含 safeline`，上限 15s；捕获"页面被刷新"异常重试；仍失败则该 URL 标记失败，不阻塞其他 |
| R3 | **防盗链 403** | 能嗅探不能下 | Referer/UA/Cookie 全链路透传，从嗅探阶段带入 yt-dlp `http_headers` |
| R4 | **批量探测慢** | 用户等待 | 三层降级（L0/L1 快速消化多数）、并发 4、流式进度、可中断、按文件夹分批 |
| R5 | **静态抓取对目标站无效** | L1 白做 | 已实测确认。L1 保留为零成本快速通道，**不作为主力**，不投入过多开发 |
| R6 | **打包 exe 体积/兼容** | 发布 | DrissionPage 为纯 Python 包（约 4MB + 依赖），不带浏览器；用系统 Edge。需回归 PyInstaller 打包，排除 `openpyxl/lxml` 等可选子依赖 |
| R7 | **DrissionPage 同步阻塞 event loop** | 后端卡死 | 一律放 `asyncio.to_thread` / 独立线程池执行 |
| R8 | **多实例浏览器资源占用** | 内存 | 单浏览器实例 + 复用标签，嗅探完成后统一 `page.quit()` |
| R9 | **通用选集提取无标准** | 覆盖率 | ✅ 已用 2 个真实样本验证（§4.6），算法落地；剩余风险为"选集不在播放页/仅存在于 XHR"的站型，按 §4.6.3 三级回退降级为单集下载，不阻塞 |
| R10 | **同一 m3u8 跨页重复下载** | 浪费 | 归一化去重（§4.3） |
| R11 | **两套后端不共享** | 范围 | 本次**只改桌面版**，NAS/Docker 版不获得该功能 |
| R12 | **依赖冲突**（已装 requests 2.34.2 等） | 环境 | 安装 DrissionPage 时已引入 requests/urllib3 升级，需回归 `pip check` 与既有测试 |

---

## 9. 依赖与环境

| 项 | 状态 |
|---|---|
| Python | venv（项目 `.venv`） |
| yt-dlp | ✅ 2026.08.19（已装） |
| ffmpeg | ✅ 9.0.2 full build（已在 PATH） |
| Playwright | ✅ 已装（chromium-1243）—— **仅用于对比验证，本方案不采用** |
| DrissionPage | ✅ 4.1.1.4（本计划实施时安装，连带 requests/urllib3/lxml/openpyxl 等） |
| 浏览器 | ✅ Edge `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` |

---

## 10. 待补充信息

**选集样本已于 2026-09-30 补齐并实测**（见 §4.6.1、附录 A.5）：样本1 播放页 195 条选集、样本2 播放页 161 条选集，两种典型结构均已验证。**P4 通用提取算法已有真实 DOM 依据，无阻塞项。**

仍需确认：

1. **需要登录才能看的站**：提供对应浏览器名（`cookiesfrombrowser` 需配对，当前样本均免登录）
2. **不同站点形态的补充样本**（可选，用于扩大覆盖率）：
   - 选集**不在播放页**、只能从详情页取的站
   - 选集数据仅存在于 XHR 响应、DOM 中完全不可见的站
   - 需要点击"展开全部"才渲染完整选集的站（虚拟滚动列表）

---

## 附录 A：实测原始数据

### A.1 样本1 WAF 穿透（DrissionPage）

```
t= 2s status=468 拦截页=True  video=0 html=17083
t= 4s status=468 拦截页=True  video=0 html=17086
t= 6s [异常] 页面被刷新，请操作前尝试等待页面刷新或加载完成。
t= 8s status=200 拦截页=False video=0 html=72913
t=10s ~ t=26s status=200 拦截页=False html=72913
最终 title='凡人修仙传 第195集 _ 厂长资源'
```

### A.2 样本2 iframe 提升（方案Z）

```
捕获 48 条去重请求，命中：
  video_info.json
  playlist.m3u8
  640x360/video.m3u8
  640x360/video0.ts ... video6.ts
>>> m3u8 = 2 条
```

### A.3 样本2 主页面关键 XHR

```
URL : https://www.cnxgct.com/user/amp/content_pframe_url?chapter_id=udWdMztqNU&level=low&expires=3600
BODY: {'data': 'https://pframe.xgcartoon.com/pframe/player.htm?vid=aa0c0684-...&reportUrl=...', 'result': True}
```

### A.4 静态抓取失败证据

```
样本1 urllib:     HTTP 403 (SafeLine)
样本2 urllib:     SSL 证书链不全 → 连接被强制重置
样本2 Playwright: DOM m3u8 = 0，网络监听 = 2
样本2 DrissionPage 主页面: 92 请求中 m3u8 = 0
```

### A.5 选集结构实测（P4 依据）

#### A.5.1 样本1 cz4k —— 播放页 `/v_play/bXZfMTEwMzAtbm1fMTk1.html`

```
链接(去重) 234 条，其中 /v_play/ 命中 195 条
参数 base64 解码:
  bXZfMTEwMzAtbm1fMQ==  -> mv_11030-nm_1
  bXZfMTEwMzAtbm1fMg==  -> mv_11030-nm_2
  bXZfMTEwMzAtbm1fMTk1   -> mv_11030-nm_195
movie_id 集合 = {'11030'}   集数范围 = 1 ~ 195，共 195 个
选集父容器 = ['DIV.paly_list_btn']            ← 注意站点拼写为 paly
详情页 = https://www.cz4k.com/movie/11030.html（含 215 条，文本"第1集…第195集"）
详情页文本另见特殊集名：虚天战纪-A-上 / 虚天战纪-A-下（混在数字序列中）
```

#### A.5.2 样本2 cnxgct —— 播放页 `/video/{slug}/udWdMztqNU.html`

```
选集元素（span 本身无 href，须取 closest('a')）:
  <div class="col-12">
    <a href="/user/page_direct?cartoon_id=shixiongashixiong-jinlei&chapter_id=BxbusWaFPB"
       class="goto-chapter chapter-box text-truncate">
      <span class="title">第01集</span>
      <span class="sequence">1</span>
    </a>
  </div>

HTML 中 chapter_id: 播放页 324 处 → 去重 161；详情页 164 处 → 去重 161
  与标题"第161集 / 更新至 161 集"完全吻合

点击第5集验证:
  before = .../video/shixiongashixiong-jinlei/udWdMztqNU.html
  after  = .../video/shixiongashixiong-jinlei/5X4Z8m9YmW.html
  → page_direct 为 302 中转，须原样请求并跟随重定向

详情页 = https://www.cnxgct.com/detail/{slug}（200，同结构；/video/{slug}/ 为 404）
面包屑给出跨域详情页 = https://www.xgcartoon.com/detail/{slug}（与 cnxgct.com 同内容）
```
