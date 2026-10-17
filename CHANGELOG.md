# 更新日志

所有重要更改都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.8.0] - 2026-10-17

> 本次围绕音乐源下载链做了根因级修复，并让歌单批量下载的 `batch_size`
> 真正生效。全量 **1307 passed / 6 skipped**，`dist\downloadkit.exe` 已
> 重新打包并做打包版端到端实测。提交：T1 `6611461`、T2 `a21803e`、
> T3/T4 `6769770`、no_proxy 加固 `d27fcd6`、0 字节空壳 `1484710`、
> 交接文档收口 `b82e51c`、motion_photo 补漏 `5808517`。

### 新增
- **下载队列按批独立并发额度（lane）**：歌单批量下载的 `batch_size`
  此前只被记进任务信息，真实并发恒为全局 `max_concurrent=3`。现在批任务
  走自己的独立额度（`DownloadTask.lane`），batch_size=5 就是 5 路并发，
  且与全局额度互不挤占。368 首歌单全量实测：全程稳定 5 路、368/368 成功、
  0 失败、28.1 分钟。取额度从派发循环移入 `_process_task`，避免某批占满
  时队首阻塞拖垮其他任务。
- **死源短路（冷却窗口）**：itzo（`music.itzo.cn` DNS 已不解析）与 migu
  （接口返回 SPA 壳）此前每首歌都白烧一次完整超时，368 首要等约 2 小时。
  连接级失败/非 JSON 响应后进入 600s 冷却，窗口内直接跳过，窗口过后自动
  重试一次（域名/接口恢复即自愈）。

### 修复
- **motion_photo.py 3 处漏网 CREATE_NO_WINDOW**（`5808517`）：ffmpeg 转码 /
  ffprobe 取尺寸 / ffmpeg 缩放挂在抖音实况照片合并主路径（默认开启），打包版
  下载实况照片会弹黑框。补标志并新增 `tests/test_no_window_coverage.py`
  全仓静态扫描（实测 15 个调用点，漏即红）防再犯。
- **kuwo 搜索恒 0 条**：`search.kuwo.cn/r.s` 返回的是**单引号伪 JSON**
  （实测 4110 个单引号、0 个双引号），原实现 `json.loads` 必然失败、
  逐行兜底又匹配不到，导致 kuwo 搜索级从未真正命中过。改用
  `ast.literal_eval` 解析（不能用 replace 引号——会破坏内容里的撇号）；
  直链兜底新增官方 `antiserver.kuwo.cn/anti.s`（实测可用，置于链首）。
- **kugou 全链路失效**：真正的病根不是"第三方源全挂"，而是 `_find_hash`
  恒取 `items[0]`，命中的往往是 VIP 曲（`Privilege=10`），官方接口对它们
  返回"需要付费"。改为**优先挑免费曲**，并把两个一直可用、却从没被接进
  兜底链的官方接口（`trackercdn.kugou.com/i/v2`、`m.kugou getSongInfo`）
  补上。实测 5/5 拿到真 MP3（修复前 0/6）。
- **general.max_concurrent 死配置**：设置页与 CLI 都能改（1~10），但
  server 从不读回，队列恒用硬编码 3。现在启动时读取并应用、设置更新时
  热生效。
- **歌单批任务永不终结**：批状态一直停在 `downloading`，前端进度条永远
  转。现在全部曲目到终态后置 `done` 并释放 lane。
- **打包版启动崩溃**：环境里带方括号的 `no_proxy`（如 Windows 约定的
  `[::1]`）会让 httpx 0.28 在解析时抛 `InvalidURL: Invalid port ':1]'`，
  而 `netease.py` 在**模块级**构造 AsyncClient —— 导入包即失败，表现为
  双击 exe 弹「启动失败」。`downloadkit/__init__.py` 在包导入最前面剥掉
  方括号条目（语义等价），兼容任何注入方。
- **取消/失败留下 0 字节假歌**：`_stream_download` 先建文件再流式写入，
  写出首字节前被取消/失败就留下 0 字节 `.mp3`（文件列表里显示成"能看见、
  播不了"的假歌）。`download_song` 失败/取消时清掉空壳，非 0 半截文件
  保留（断点续传依据）。
- **异常不再静默**：kuwo/kugou/migu 降级分支的 `logger.debug/info` 按
  §3.4 约定提为 `logger.warning` 并带 `type(e).__name__`。

### 测试
- 全量 **1309 passed / 6 skipped**（较 v0.7.0 基线 1278 净增 31 例）：
  新增 `tests/test_batch_concurrency.py`（11）、`test_platforms.py` kuwo/kugou
  回归 + 死源短路（若干）、`test_no_proxy_sanitize.py`（4）、
  `test_downloader.py` 空壳清理（4）、`test_no_window_coverage.py`（2）。
  注：`test_douyin_browser*` / `test_douyin_e2e` 3 个文件需要独占 browser
  profile，**打包 exe 在运行时它们会挂起**——exe 关闭时跑全量 1309/6，
  exe 运行中排除后 1281/3（本批发版前实测口径）。
- 打包版端到端实测（毒化 no_proxy 环境启动 + 单曲 + 5 路批量 + 取消）全部通过。

### 文档
- `docs/T3-368首歌单全量实测记录-2026-10-17.md`：全量跑的并发曲线、源命中
  分布、数据质量点（3 首源侧仅 5-6s 试听、2 次 kuwo CDN 410）。

## [0.7.0] - 2026-10-16

### 新增
- **补齐四块测试空白**（v0.6.0 遗留的 4 个测试任务 T1–T4，纯测试无功能改动）：
  - **服务端 `/api/cookies/*` 单测**（`tests/test_server_cookies.py` 16 例）：`open-login` 平台 URL 分支与 `webbrowser.open` 异常兜底、`load-from-browser` 的文件/浏览器/读取失败三路径、`save` 落盘与参数校验；monkeypatch `webbrowser.open`（`webbrowser` 是函数内局部导入，只能在 `webbrowser` 模块上打）和 `pathlib.Path.home`（把保存路径引到临时目录，不污染真实 `~/.downloadkit/`）
  - **平台适配器单元测试**（`tests/test_platforms.py` 45 例）：netease 解析函数 18 例 + 静态方法 6 例、qqmusic `match_url`/`extract_playlist_id` 4 例、migu `_clean_artist` 4 例、gequbao `_find_aid`/`_parse_app_data`/`_extract_download_url` 7 例、itzo 搜索匹配 5 例。**全部直连模块纯函数，不发网络请求**；测试按实际行为修正了三处先验（`_parse_song_item(None)` 返 None 而非抛异常、`_parse_year(0)` 返 0 而非 1970、gequbao 正则要求 `<a href="/music/NNN">` 格式）
  - **search / download / playlist E2E**（`tests/test_e2e_full_flow.py` 扩 4 条链路 16 例）：真起 uvicorn 端口 8792 复用 module 级 fixture，验参数校验（缺字段 422、空值 400）与响应结构（`songs[]` 含 title/artist/platform/song_id、`task_id` 返回、未知任务 404、`song-info` 正确提取网易云与 QQ音乐的 song_id/platform）；离线环境对网络依赖路径做容忍（歌单解析 200 或 400 皆可）
  - **书签导入服务端单测**（`tests/test_server_bookmarks_import.py` 13 例）：直连 `api_bookmarks_import` 路由，覆盖正常树结构与统计、空/纯空白/非书签 HTML/0 条 http 链接四个 400 分支、BOM 前缀剥离、丢 DOCTYPE 的工具导出、`javascript:`/`ftp:` 不计数、空标题 `<a>` 不计数、残缺 HTML 靠 `close()` flush 未闭合标签保留已解析部分
- **版本号同步到 0.7.0**：4 处（`pyproject.toml` / `cli.py` `version_option` / 关于页 / `downloadkit.iss`），由 `tests/test_version_sync.py` 钉死

### 测试
- 全量 **1245 passed / 7 skipped**（1252 collected = 1214 单元/CLI + 38 离线 E2E），较 v0.6.0 的 1216 净增 29 例
- `TESTING.md` 计数改为实测真数，并纠正 1.1 节历史虚高（原写 ~805，实际收集 1252）

## [0.6.0] - 2026-10-16

### 新增
- **CLI 收藏歌单命令 `collections`**（P5-7；此前收藏只能在界面里操作）：`list` 列全部歌单、`show <ID>` 看详情与缓存曲目（`-n` 截断）、`add <链接>` 收藏（`-n` 自定义名称）、`rename <ID> <名>` 改名、`rm <ID...>` 删除（摊开列出目标并确认，`--yes` 跳过）、`refresh <ID...>` 重新解析并替换缓存曲目
  - 走 HTTP：歌单缓存在**服务端**的 `~/.downloadkit/collections.db`，而且 `add` / `refresh` 都会真去解析歌单（网络 + 各平台适配器），CLI 自己再实现一遍就是两套解析逻辑，两边对不上时谁也说不清哪个是真的
  - **退出码沿用「状态查询」组的约定**：「歌单不存在」「歌单解析失败」是业务结果而不是「没做成该做的事」，打完提示退出码仍是 0；只有用法错误（ID 不是整数、参数缺失）才是 2。与 sniff / bookmarks / proxy-test 那组探测器的「没抓到就 1」不混用
  - 实测处理三个点：① 歌单 ID 直接拼进 `/api/collections/{id}`，非数字会回 404 —— 用户以为「歌单不存在」其实是 ID 敲错了，本地拦下并分开说；② `rm` 逐个 DELETE（没有批量端点），先 GET 列表把 ID 换成「ID + 名称 + 链接」再确认，全都不存在时连确认都不问；③ `list` 表格不放 URL（60+ 字符会把名称列挤没，真正要复制的是 ID，完整字段 `--json` 都有），歌单链接本身走 `click.echo` 不走 `console.print`
- **修复：歌单收藏模块两个真 bug**（此前整个仓库没有一处覆盖 `downloadkit/collection.py`，一直没人发现）
  - `refresh_collection` 的 SELECT 少了 `auto_name` 却去读它 → 必然 `IndexError`，**`POST /api/collections/{id}/refresh` 从来就没工作过**，每次刷新都是 500
  - `_run_async` 的 `except RuntimeError` 罩住了整个 try 块，把解析器抛的 RuntimeError 当成「没有事件循环」再跑一次 `asyncio.run`，真报错被盖成 `asyncio.run() cannot be called from a running event loop`（DrissionPage 一类浏览器驱动很爱抛 RuntimeError）。收窄 except 作用域，实测 OLD/NEW 对比：`OLD: asyncio.run() cannot be called from a running event loop` → `NEW: 真正的错误`
  - `tests/test_collection_refresh.py` 11 例：刷新成功、清空旧曲目再插新的、`song_count` 同步、`auto_name` 开/关对名字的处理、解析失败保留旧缓存、`_run_async` 三种异常路径
- **离线实测手法**：替身只挂 `downloadkit.collection.parse_playlist` 一个点，于是真 FastAPI 路由、真 URL 去重、真 SQLite 写入、真曲目缓存、真刷新逻辑全照跑，只有网络解析是假的；改替身读的 JSON 就能让 refresh 真的把曲目数改掉。`tests/test_cli_collections.py` 50 例；离线实测 64/64（建/删/改名/刷新都直接读 `collections.db` 对账，含级联删曲目、刷新前后用不同数据以证明替换是真的），全量 1006 passed
- **CLI 下载历史命令 `history`**（P5-7b；此前历史只能看界面）：**先补服务端 5 个端点**——`GET /api/history?limit=&offset=` 列表、`POST /api/history/search?keyword=` 搜索（query 参数）、`DELETE /api/history/{id}` 删单条、`POST /api/history/clear` 清空、`GET /api/history/count` 计数；CLI 暴露 `list [-n] [-o]`、`search <关键词> [-n]`、`rm <ID...>`、`clear`、`count`；退出码沿用「状态查询」组的 0；两个坑：search 端点是 query 参数不是 JSON body、rm 判断 ID 存在性要 GET list 不能靠 count；`tests/test_cli_history.py` 29 例；离线实测 29/29
- **P5-8 收尾**：`download` / `playlist` 命令补 `-o/--output` 输出目录选项，`downloader.download_song` 同步支持 `output_dir` 参数；全命令 `--help` 中文化（search/download/playlist/douyin 等命令此前混有大量英文 docstring 和提示文案）；新增 `tests/test_cli_music.py` 12 例覆盖 search（选曲/空结果/退出）、download（URL 校验/-o 传递）、playlist（下载/取消/空歌单），底层异步函数用协程替身替换不发起真实网络请求
- **P5-9 书签批量探测 `bookmarks probe`**：`bookmarks probe <文件> [--l2] [--no-l2] [--urls] [-n/--limit] [--json]`，从书签 HTML 提取链接并批量探测可用流（L0 直链 → L1 静态 → L2 浏览器，三层降级），轮询进度后展示命中/未命中表格；退出码沿用探测器组约定（exit 1 连不上）；`tests/test_cli_bookmarks_probe.py` 9 例
- **CLI 设置命令 `settings`**（P5-6；此前改配置只能在界面里点）：`get [键]` 看配置（不给键全量列出、给键只回值，`--json` 原样返回含系统代理探测）、`set <key> <值>` 改配置、`proxy-test [代理地址] [--url 目标]` 测代理或直连通不通（不给地址就是测直连）
  - 「Cookie 路径设置」= `cookie.douyin_path` / `cookie.bilibili_path`，由通用 `set` 覆盖，不单独开命令
  - 走 HTTP：配置文件在**服务进程**的 HOME 下，CLI 自己写会写到另一份配置里；而且有些项保存后是服务进程当场改内存的（`history_max_records` 保存时就 `update_max_records`），直连模块只会弄出「文件改了、内存还是老值」的分裂
  - **`/api/settings/update` 只收 `general`/`proxy`/`cookie`**：传 `subscription` 时 `config` 为空，它照样回 `{"status": "ok"}` 却什么都没写 —— 假成功，本地拦下并指向 `subscribe poller on|off|set`
  - **`set` 按该键默认值的类型解析**（bool 认 on/off/yes/no/1/0）：int 写成字符串下次读的人 `int()` 直接炸；bool 更要命——`bool("false")` 是 True，等于把开关悄悄反了。数值范围抄产品自己的限制（`index.html` 的 min/max），`max_concurrent < 1` 会让下次启动的 `asyncio.Semaphore(0)` 把所有下载卡死
  - 实测修掉四个坑：① **`proxy.mode` 写非三态值会被 `resolve_mode` 静默忽略**（设了等于没设），必须收口当场报错——而它恰恰是命令行最该能设的一个（界面三态落盘字段，`DEFAULT_CONFIG` 里没有）；② **下载目录键先过服务端 `download-dir-info` 再落笔**，顺序反了就把配置指向用不了的路径；③ **回执读服务端返回的实际存值**而不是把自己刚发的再念一遍，对不上就不喊成功；④ 全量列出走 `click.echo`——键值是路径，rich 按 80 列折断了就不是原值（P5-5 流地址同一个坑）
  - 退出码沿用 P5-5 的分组语义：`proxy-test` 是探测器（服务端**永远回 200**，通不通在 body 的 `ok` 里）→ 0 通 / 1 不通；键不存在、类型不对、范围越界是用法错误 → 2（走 stderr）
  - `tests/test_cli_settings.py` 65 例（含「键表里每一项都得能设进去」的全键遍历，漏一项就是死键）；离线实测 67/67（配置**真落盘**：每步 `set` 后用 `tomllib` 读回 `config.toml` 比对，被拒的用例按字节数断言一个字节都没写；`proxy-test` 只打本地起的 HTTP 服务或没人监听的端口，全程 0 外网请求），全量 945 passed
- **CLI 嗅探与书签 `sniff` / `bookmarks`**（P5-5；此前嗅探和书签导入只能在界面里做）：`sniff <url>` 真实浏览器深度嗅探（`-t/--timeout` L2 预算、`--json` 原样返回）、`bookmarks import <文件>` 导入浏览器导出的书签 HTML 并批量解析出全部链接（默认缩进树视图、`--urls` 去重一行一个管道友好、`-n/--limit` 截断、`--json`）
  - 走 HTTP：L2 嗅探用的是服务进程里那个 DrissionPage 浏览器单例（`_lock` 串行、headless/有头按站点在进程内记忆），CLI 自己再起一份就是两个浏览器抢资源，还会丢掉「这个站回退过有头」的进程内记忆
  - **退出码按组定语义**：这一组是探测器——没抓到流、导不进链接都是「没做成该做的事」→ 1（含连不上），脚本据此分支不必解析中文；与 `queue`/`subscribe` 那两组「状态查询查到空也算成功」的 0 不冲突，各自写进 docstring
  - 实测修掉五个坑：① 流地址必须走 `click.echo` 不能走 `console.print`——m3u8 动辄上百字符，rich 按 80 列会从中间切断，复制出来是断地址（P5-2 Task ID 同一个坑，那次是 `no_wrap`，这里整行本身就超宽只能绕开 rich）；② 客户端超时要给足 L2 预算余量，退成默认 30 秒会「服务端还在干活、客户端先报超时」；③ `nav_failed`（死域名）与被 WAF 拦必须分开提示，否则用户对着打不开的地址反复重试；④ 书签解码 UTF-8 **真解不开**才退 cp936，反着来会静默出乱码却照样解析成功，`--json` 侧本地失败也要吐 `{"error": …}` 而不是走 stderr；⑤ 书签标题带方括号不 escape 会被 rich 当标记吃掉
  - **离线实测用替身嗅探器**挂在 `server.sniff_l2` 上，真实路由、真实 `is_http_url` 校验、真实 `timeout` 裁剪、真实序列化全照跑，替身把裁剪后的 timeout 记进文件用来断言 `-t 999` → 60、`-t 5` → 10；书签侧不换任何东西，真写文件真走服务端 `parse_bookmarks_html`（含 cp936 解码链路与三个 400 分支）
  - `tests/test_cli_sniff.py` 55 例；离线实测 56/56（服务未起先测连不上），全量 880 passed
- **CLI 文件管理命令 `files`**（P5-4；此前删文件只能在界面里点）：`ls [分类]` 列下载目录（分类 music / videos / images / animated / others，按修改时间倒序，`--json` 纯 stdout 管道友好）、`rm <路径...>` 删文件（删之前摊开列出目标并确认，`--yes` 跳过确认）、`open <路径>` 用系统默认程序打开（`--dir` 改为打开它所在的目录）
  - 走 HTTP：下载根目录由服务端按配置算出（`get_download_dir()`，可能指向 NAS、也可能带自定义分类子目录），CLI 本地猜路径很容易对不上；路径安全同样交给服务端 `safe_delete_path` 统一拦，CLI 不重复实现一遍安全逻辑
  - 实测修掉三个坑：① `batch-delete` 逐条记账——单条失败整个请求仍回 200（逐条 `errors`），所以删失败必须逐条列出来，否则用户以为全删干净了；② 文件名是用户内容，`坏[1].mp3` 不 escape 会被 rich 当标记吃掉，显示的名字就和真实文件名对不上；③ 容器 / headless 环境下 `open` 弹不开程序，服务端只回「文件在哪」，CLI 照原样转述而不是谎称「已打开」
  - `tests/test_cli_files.py` 60 例；离线实测 49/49（真铺 6 个媒体文件真删 + 收尾按磁盘清单比对），全量 825 passed
- **CLI 订阅命令 `subscribe`**（P5-3；此前订阅只能在界面里操作）：`add <链接|sec_uid>` 加订阅（默认抓主页拿昵称，`--no-profile` 跳过、`--scope`/`--backfill` 定范围）、`list` 列订阅 + 总览、`remove` / `rm` 取消、`scope` 改下载范围（`new` / `backfill N` / `all`）、`check <创作者>` 单查（`--dry-run` 只看不下载）、`check-all` 全查、`poller` 定时器（裸命令看状态，子命令 `on` / `off` / `set`）
  - 与 `queue` 命令组同源走 HTTP：浏览器实例和定时器轮次都活在服务进程里，CLI 不直连模块；连不上服务给「这个命令需要 DownloadKit 正在运行」+ `--server` 指引，而不是裸 traceback
  - **范围短写只做翻译不做校验**：`new`→`only_new`、`backfill`→`backfill_n`、`all`，真正的合法性由服务端 `validate_scope` 定夺；`backfill` 缺 N / 非 backfill 多给 N / 未知值一律本地拦截不发请求。范围改成 `all` 需确认（`--yes` 跳过），创作者已配 `all` 时 `check` 同样要确认
  - 实测修掉四个坑：① `check-all` 不给 `--scope` 时 body 必须传 `scope: None`（传空串服务端 400）；② `poller set` 只给 `--daily-at` 推断 `daily_at`、只给 `--interval` 推断 `interval`、两个都给必须显式 `--mode`；③ 创作者解析三层「昵称精确 → 唯一前缀 → 唯一子串」，多义或无命中一律列候选绝不猜；④ rich 80 列折行会把「现有 5 个作品」从中间切断，实测断言必须折行免疫
  - **离线实测改用替身浏览器**：先试的「禁用 Chromium」方案不成立——`PLAYWRIGHT_BROWSERS_PATH` 指空目录只会让启动时预热失败，代码会回退 `channel="msedge"` 启动系统 Edge（`douyin_browser.py:298`），照样产生真实抖音流量。改为在 `import server` 之前把 `downloadkit.douyin._browser_instance` 换成替身对象，`get_browser()` 见实例非空直接返回、`DouyinBrowser.start()` 根本不会被调用；替身读一个 JSON 配置，于是「建基线」「发现新作品」「掉登录态」这些分支能在同一次起服务里反复触发，而 `check_creator` 全套真实逻辑照常跑。订阅库再用 `USERPROFILE`/`HOME` 重定向隔离
  - `check-all` 撞 `LoginRequired` 会 break：只记 1 条失败，`total` 仍是创作者总数（实测 2 个创作者 = 「创作者 2 · 失败 1」+ 显式 `stopped_at`），不会假装后面几个检查过了
  - `tests/test_cli_subscribe.py` 101 例；离线实测 106/106（替身浏览器、全程 0 下载任务、真实订阅库 mtime 未变），全量 765 passed
- **CLI 队列命令 `queue`**（P5-2；此前队列只能在界面里操作）：`queue list [all|active|done|failed]` 列任务（`--json` 纯 stdout 管道友好）、`pause` / `resume` / `cancel` / `retry` 单任务操作、`retry-failed` 一键重试全部失败（`retried`/`orphaned` 转述）、`rm` 移出列表、`open` 打开产物文件并对齐界面「打开成功才移除」的行为
  - 新增全局 `--server`（环境变量 `DOWNLOADKIT_SERVER`，默认 `http://127.0.0.1:8765`）
  - **队列状态是服务进程的内存态**（`download_queue.active_tasks` + `server._downloads`），CLI 一律走 HTTP 读写正在运行的服务，不直连模块（直连只会看到空队列）
  - 实测修掉三个坑：① rich 在 80 列终端会把 40 字符 Task ID 压没 → ID 列 `no_wrap` 全长可见、失败原因挪到表格下方整行显示；② `pause`/`resume`/`cancel` 服务端是 fire-and-forget（`DownloadQueue` 只记标志位，任务不存在也回 200）→ CLI 先查队列拦下不存在任务，不给假成功；③ 连不上服务给中文指引（`--server`）而不是裸 traceback
  - `tests/test_cli_queue.py` 24 例；离线实测 22/22（真起服务 + 真实入队下载 + headless open-file），全量 660 passed
- **CLI 视频命令 `parse` / `video`**（此前 CLI 只有音乐四命令，视频链路只能走 UI）：
  - `downloadkit parse <url>`：解析不下载，覆盖抖音/B站/YouTube/小红书/通用网页（generic 兜底），显示标题/作者/时长/封面/可用格式。选项：`--json`（机器可读，管道友好）、`-e/--episodes`（展开选集，与 `/api/video/episodes` 同参）、`--referer`（generic 防盗链）、`--name`（命名提示 → suggested_name）
  - `downloadkit video <url>`：解析+下载。选项：`-q best/1080/720/480/360`（YouTube/generic）、`-o` 输出根目录（抖音再建 videos/images/animated 分类子目录，其余平台直接落该目录）、`-e` 展开选集批量下载 + `-n 1,3 / 1-5 / a` 选集、`--referer`、`--name`
  - 平台分发抽到新模块 `downloadkit/video_service.py`（`detect_platform` + `parse_url` + `download_parsed`），输出结构与 `/api/video/parse` 响应契约对齐；`server.py` 的本地 `detect_platform` 改为 import 自该模块（行为 100% 不变）。HTTP 路由层的平台分发保持不动——它耦合任务队列与下载历史，该区域零测试覆盖，重构收益不抵回归风险
  - 顺带修正 `main()` docstring（原文谎称支持 Bilibili/YouTube/Xiaohongshu，实际此前无视频命令）
- **修复（随 CLI 暴露）：INFO 日志污染 CLI stdout**——`downloadkit/logger.py` 在 import 时就给 `downloadkit` logger 挂了 stdout handler（INFO 级），server 服务端这样正合适，但 CLI 的 stdout 是给用户/管道看的：INFO 日志盖过 rich 界面，`--json` 时直接产出非法 JSON。CLI 启动时把该 logger 压到 WARNING（`--json` 模式压到 ERROR），并加 `-v/--verbose` 一键恢复详细日志
  - 实测：离线测试场（本机 3 mp4 + http.server）覆盖直链解析/JSON 输出/选集展开/单集下载/批量下载，加抖音图文真实链接解析+下载，30/30 PASS；新增 `tests/test_cli_video.py` 43 例（平台分发/各平台输出结构/落点透传/选集选择/server-CLI 共用同一 detect_platform）

### 修复
- **`download_content` 的 `output_dir` 被静默忽略，CLI 的 `-o` 形同虚设**：该参数的 docstring 标着「已废弃，现在使用分类子目录」，但参数本身还在、且各分支一律改用 `get_download_subdir()`——调用方传什么都落空，实测连传三次都写到配置目录。改为新增 `_resolve_out_dir(category, output_dir)` 统一解析：`None` → 仍走配置的分类目录（**含 `download_dir_video` 等自定义子目录，历史行为 100% 不变**），指定 → 落 `output_dir/{videos,images,animated}/`。同步把 `server.py` 两处原本传 `get_download_dir()` 的调用改为不传（传了会绕过自定义分类目录），`fetch()` / `download_video()` 默认值改为 `None`，CLI `-o` 默认改 `None` 并修正 help 文案（原写着 `default: ./downloads` 却不生效）。实测：指定目录 5/5 落对位置且零泄漏、`None` 回到配置目录、重复调用不下第二份
- **图文扩展名与实际内容不符（`.jpg` 装的是 WEBP）**：`resolve_note` 返回的 `file_ext` 写死 `jpg`，但抖音图文接口实际返回 WEBP（实测 5/5），于是文件名与魔数不一致——看图软件靠嗅探能开，按扩展名判断的工具会认错。落盘后按魔数校验，不符则**只改名不重编码**（不引入有损压缩、不依赖可选的 Pillow），支持 jpg/png/webp/mp4。配套修 `_existing_target`：候选名（`.jpg`）不存在时按同名 stem 找其它媒体扩展名，否则改过名的文件会在下次被认成「不存在」而重下出第二份；`tests/test_douyin_output_dir.py` 22 例覆盖
- **断点续传跨源拼接（可能产出损坏音频）**：`_stream_download` 原先只要目标文件存在就带 `Range` 续传，但五级回退共用同一个文件名——前一源写了半截、后一源支持 206 就会从半截处接着写，两段不同音频被拼进同一个文件。改为记录「半截文件属于哪个源」，只有**同一个 URL** 才续传；换了源或来源不明（进程重启）一律丢弃重下（宁可多下一次，也不产出拼接坏文件）。同源续传与未知来源重下均有回归脚本验证
- **取消/暂停被当成「这一级失败」**：`_stream_download` 的 `except Exception` 连 `CancelException` / `PauseException` 一起吞掉，用户点取消后引擎会继续试下一级源接着下。改为这两类异常先于通用捕获向上抛
- **itzo 兜底源与 Step 1 完全同源，等于白跑一级**：itzo 固定请求 `type=netease`，返回的就是 `music.163.com/song/media/outer/url`，VIP 歌曲必然和 Step 1 一起吃 HTML。改为按优先级尝试 `("qq", "netease")`——`type=qq` 返回带 vkey 的真实 QQ 直链（独立源），netease 留作偶发网络失败时的二次机会
- **非 MP3 内容被写成 `.mp3`**：itzo 的 QQ 直链是 m4a，原先会原样落盘成 `.mp3`（文件名与内容不符、ID3 也打不进去）。落盘后按魔数校验，非 MP3 则用 ffmpeg 转码为 MP3；转不出来就丢弃并让位给下一级源（ffmpeg 缺失时同理）
- **yt-dlp 兜底「下成功了却报失败」**：命令带 `--max-downloads 1`，yt-dlp 下载完成后以 rc=101（Aborting remaining downloads）退出，老逻辑要求 rc==0 才认，把完整落盘的音频报成 `All yt-dlp sources exhausted`。改为以产物文件是否本次新写出为准（大小 + mtime 指纹，避免误认上次中断的残留），退出码只用于报错信息；同时复用 `generic_video._yt_dlp_cmd()` 定位 yt-dlp（修掉 frozen 下可能 spawn 应用本体的隐患），并把原先写在 `return` 后面永远执行不到的 stderr 日志挪到会执行的位置
- **歌曲宝（gequbao）全链路失效**：站点改版后搜索页去掉 `data-aid`、音乐页不再内嵌 mp3 直链，直链改由内联 `window.appData` 的 `play_id` 换取。已适配 `POST /member/common-play-url`（`id=play_id, purpose=play`），解析人机验证/次数用尽等业务码并优雅跳过；换到的酷我 CDN 直链**带 gequbao Referer 会 403**，链路依赖 `_stream_download` 只对 163 加 Referer 的现有行为（代码内已注明）。另修 GET 偶发 `Server disconnected` 导致的 ReadTimeout——改为有限重试并重开连接，去掉每次下载往工作目录写调试 HTML 的 `_dump_debug`
- **咪咕（migu）源每次下载刷一条 ERROR**：旧搜索接口改版后 301 到 `/v5` SPA 壳，`resp.json()` 必然 `JSONDecodeError`。改为先按 content-type 判断非 JSON 响应，识别为该源已失效并返回 None（INFO 一条），让位给 yt-dlp；请求层异常同样兜住不再上抛

## [0.5.0] - 2026-10-04

### 新增
- **批量资源嗅探下载（P0~P5）**
  - 通用视频解析下载引擎：L0 直链 → L1 yt-dlp 静态解析 → L2 浏览器嗅探三层降级，任意网页视频/图文链接可解析下载
  - 浏览器书签导入：按文件夹勾选 → 批量并发探测（三层降级流水线、实时进度、可停止）
  - 播放页选集展开（静态提取三级回退）→ 勾选探测 → 批量下载，按剧名建子目录落盘
  - 选流勾选：多条流命中时手动选择入队；解析期 Referer 全程透传（防盗链站）
  - 深度嗅探入口：解析失败一键 L2（DrissionPage + Edge 过 WAF），命中结果内嵌展示
- **影视解析独立成主导航 Tab**：书签导入 → 探测 → 批量下载的影视链路从「资源解析」拆出
- **影视解析 Tab 支持手动输入链接**：顶部与资源解析同款多行输入框（单行回车解析一条、多行自动批量），解析结果、失败态兜底按钮与嗅探结果全部落在本 Tab 容器；下方保留书签批量导入，两段以分节线分隔
- 订阅与设置增量（P1~P3）：代理三态与测试连接、队列一键重试全部失败、设置导出/导入、解答页搜索、托盘菜单快捷项、订阅卡片上次检查状态、音乐页/资源页下载按钮状态统一

### 变更
- **社交解析合一**：「单个链接 / 批量下载」两个模式合并为一个多行输入框——单行回车解析一条，多行每行一个链接自动批量（Shift+Enter 恒换行），输入框 1~6 行自适应
- **文案一致性**：进行时态统一（横幅「正在 X…」、按钮「X 中…」、省略号统一全角 …）；资源解析 hint 与控件对齐（原 hint 声称支持多行、控件却是单行）；书签 0 链接空态提示
- **解析请求整体超时**：AbortController 超时（单条 120s、批量按条数放宽、嗅探 120s、选集 150s），超时转可读错误并给深度嗅探/展开选集兜底，不再无限转圈
- **慢接口耗时日志**：解析/嗅探类 4 个接口记录起止耗时（其他接口 >5s 也记），配合阶段日志定位「一直解析」类问题

### 修复
- **打包版解析影视链接「一直解析」超 2 分钟 + 中途弹「已在运行」窗口**：frozen 下 yt-dlp 子进程命令拿 `sys.executable` 当解释器，spawn 出的是 downloadkit.exe 本体 → 撞单实例锁弹模态框、父进程 45s 超时。修复为同目录/PATH 查找独立 yt-dlp，都没有时降级进程内 Python API（输出与 `--dump-json` 对齐，开发环境行为不变）
- **exe 排障日志缺失**：windowed EXE 里应用 logger（server / downloadkit.*）root 上无人接收，[API] 耗时行、[Generic] 阶段行、下载开始/完成行全部丢失——run.py 给 root 挂文件 handler 接进 downloadkit.log
- 死端口 L2 探测误报 WAF（导航失败页提前退出 + 三层错误文案区分）；WAF 类 miss 自动重试 1 次

### 打包
- PyInstaller 收全 DrissionPage（延迟 import 动态子模块）与 yt_dlp（extractor 插件），构建预检清单同步

### 测试
- 全量 pytest 561 passed / 6 skipped（新增 yt-dlp 命令分支与进程内降级分派 7 例）
- 8899 本地源闭环：书签导入 → 探测 10/10 → 选集展开 → 批量下载 ftyp 校验 PASS
- exe 实测：解析 1.7~3.5s 内返回、全程无第二实例无弹窗；双开正确识别并激活已有实例；UI 三 Tab 走查 console 0 错误、0 个 4xx/5xx

## [0.4.1] - 2026-09-27

### 修复
- **创作者订阅「订阅」「预览」一按就报
  `argument of type 'DouyinBrowser' is not iterable`**：`subscription_service`
  调 `resolve_short_url(browser, text)` 时实参顺序写反了，而签名是
  `resolve_short_url(url, retries=3, browser=None)`，于是 url 收到的是浏览器
  对象，函数里 `if "v.douyin.com" not in url` 直接 TypeError。两个按钮都先走
  `_resolve_sec_uid()`，所以一起炸
- 同一处还把**整段分享文案**当 URL 传了进去：httpx 对没 scheme 的输入不报错，
  而是拼出相对路径、send 时才失败 → 白跑满 3 次指数退避（约 6 秒）→ 浏览器
  兜底也失败 → 最后报一句误导性的「短链跳转后没找到创作者 ID」。现在先抽出
  纯短链再传，`resolve_short_url` 入口也加了规整兜底
- `build/test-exe-tray.py` 在中文（GBK）控制台打印 `«»` 抛
  `UnicodeEncodeError`，脚本崩在第 7 步：保留原编码、打不出的字符替换成 `?`，
  4 处 `«»` 换成 ASCII `[]`
- 窗口 1280×800 且默认落在屏幕左上角（pywebview 不传 x/y 的默认行为）：
  改为 1120×700，并按工作区（扣掉任务栏）居中，另加 `min_size=(1000, 640)`
  防止拖太小把布局挤烂

### 优化
- **下载目录归到总文件夹**：默认根目录 `~/Downloads` → `~/Downloads/DownloadKit`，
  `music` / `videos` / `images` / `animated` 四个分类目录收进总文件夹，
  不再直接散落在系统下载目录下
  - 旧配置值（`./downloads/*`、`~/Downloads/*`）启动时**一次**跳到最新默认
  - 旧分类目录里的已有文件一次性搬进总文件夹：同名改名 `(1)` 绝不覆盖，
    单个搬不动的留在原地、源目录非空绝不删除，Docker（`MUSIC_DL_DIR`）跳过
  - 设置页改总目录时，没单独自定义过的分类目录跟着一起改
- `test-exe-tray.py` 的下载红线基线跟随新路径 `Downloads\DownloadKit\videos`

### 测试
- 新增 `tests/test_resolve_sec_uid.py`（12 例）：钉死上面两层根因。
  此前 11 处 `resolve_short_url` 用例全是直接调函数，没有一条走
  `_resolve_sec_uid` 这个唯一调用方，所以这个 bug 一路溜到了线上
- 新增 `tests/test_download_dirs.py`（20 例）：默认值、配置多跳迁移、
  文件搬迁三条安全红线、幂等
- 全量 `pytest`：**249 passed, 6 skipped**

## [0.4.0] - 2026-09-26

### 新增
- 抖音创作者订阅与自动增量下载（A1-A5）：用 `baseline_max_id` 水位线
  只捡基线之后的新作品，首次订阅只建基线、不回补历史；检查串行不并发，
  避免撞抖音限流
- 抖音扫码登录，登录态持久化在独立 profile，跨重启复用（扫码只需一次）
- 抖音浏览器启动链：优先系统 Edge，Playwright 自带 Chromium 兜底，
  两者都不可用时给出含操作指引的报错
- Windows exe 一体化打包（PyInstaller onefile），playwright driver
  随包分发，双击即可用抖音
- 歌单收藏、下载后元数据补全与 ID3 标签写入
- 设置页目录选择与 Cookie 登录流程
- NAS Docker 部署路径与下载目录挂载
- 打包前环境预检 `build/check-build-env.py`，exe 实测
  `build/test-exe-douyin.py`（登录态、订阅读取、真实抓取）
- 开机自启动：写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
  （当前用户，不弹 UAC），设置页开关勾完立即生效，非 exe 模式如实提示
  不可用而不是让用户点了没反应；注册表测试打在临时键上，不碰用户真键
- 关闭窗口时最小化到托盘（pystray）：窗口收进后台、订阅轮询与下载不中断，
  托盘菜单提供「显示主窗口 / 退出」；未开启该开关时关闭仍等于退出，
  原行为不变。exe 实测 `build/test-exe-tray.py`（注册表读写、托盘创建、
  WM_CLOSE 两种关闭路径、红线复核）
- 新手使用说明（图文）`docs/使用说明.md`：覆盖启动、扫码登录、订阅、
  自动检查、下载目录、开机启动与托盘、常见问题，4 张实测截图存
  `docs/images/`；README 顶部给入口（小白不会自己去翻 docs/）
- 静态资源引用一致性测试 `tests/test_static_refs.py`：扫描 9 个 JS 文件
  约 190 处按 ID 取元素的写法，断言目标真的存在于 index.html，
  再配关键锚点 ID 与 1.5 两个开关的两侧齐全性检查

### 优化
- 项目合并：Windows 桌面版与 NAS Docker 版统一到一个仓库
- 打包脚本绑定项目 .venv，避免 PyInstaller 分析到错误环境

### 修复
- PyInstaller `excludes` 误排除 playwright，导致 exe 内抖音功能全部失效
- PyInstaller `excludes` 误排除 PIL/Pillow（按「大而无用的库」一刀切），
  导致 exe 内托盘图标、实况照片、抖音图片处理全部拿不到 Pillow
  （`run.py` / `motion_photo` / `douyin` 三处引用一并受影响）
- 歌单「全部下载」点了毫无反应：`music.js` 里 `downloadPlaylistSongs()`
  引用了根本不存在的 `#playlist-clear-btn`，`null.style` 抛 TypeError，
  而这行排在 `state.songs = songs` / `renderResults()` **之前**，
  整个批量下载分支一次都没执行过。静态读代码看不出来，只有真点一次
  才会暴露——已修复并用 `tests/test_static_refs.py` 钉死防止复发
- 两处过期注释仍写「增量下载（A4 尚未实现）」，而 A4 早已实现：
  `server.py` 订阅分组的依赖链、`subscription_service.py` 抓列表的说明
- 抖音浏览器启动失败时未释放 playwright driver，轮询每失败一次就泄漏
  一个进程
- 安装包版本号写成 1.0.0，与项目版本无关
- 版本号三处互不相同（pyproject 0.3.0 / CHANGELOG 0.3.1 / 安装包
  1.0.0），统一为 0.4.0

### 移除
- 影视搜索全部代码及其引用

## [0.3.1] - 2026-06-01

### 新增
- Web UI拆分重构，从3500行单文件拆分为7个模块文件
- 创建`utils.check_download_status()`公共函数
- 补充测试覆盖，总计60个测试通过
- 补全依赖声明，添加biliup可选依赖
- 创建ARCHITECTURE.md架构文档
- 创建CHANGELOG.md更新日志

### 优化
- 统一日志框架，使用logging模块替代print语句
- 消除重复代码，提取公共函数
- 优化项目结构，提高可维护性

### 修复
- 修复douyin.py中的暂停/取消检查重复代码
- 修复xiaohongshu.py中的暂停/取消检查重复代码
- 修复downloader.py中的暂停/取消检查重复代码

## [0.3.0] - 2026-05-30

### 新增
- 修复文件接口路径安全漏洞
- 修复下载历史记录功能
- 统一下载队列管理
- 限制CORS配置
- 添加边界测试用例
- 更新文档

### 优化
- 优化下载队列并发控制
- 优化文件安全验证
- 优化错误处理

### 修复
- 修复路径遍历攻击漏洞
- 修复下载历史记录丢失问题
- 修复CORS配置过于宽松问题

## [0.2.0] - 2026-05-28

### 新增
- 添加小红书下载支持
- 添加实况照片功能
- 优化下载队列

### 优化
- 优化视频解析逻辑
- 优化下载速度
- 优化用户体验

### 修复
- 修复抖音解析失败问题
- 修复B站下载中断问题
- 修复YouTube下载慢问题

## [0.1.0] - 2026-05-27

### 新增
- 初始版本
- 支持音乐下载（网易云、QQ音乐）
- 支持视频下载（抖音、B站、YouTube）
- Web UI界面
- CLI命令行工具
- 下载队列管理
- 下载历史记录

---

## 版本说明

### 版本号规则
- **主版本号**: 不兼容的API更改
- **次版本号**: 向后兼容的功能性新增
- **修订号**: 向后兼容的问题修正

### 更改类型
- **新增**: 新功能
- **优化**: 性能或体验改进
- **修复**: Bug修复
- **废弃**: 即将移除的功能
- **移除**: 已移除的功能
- **安全**: 安全相关的更改
