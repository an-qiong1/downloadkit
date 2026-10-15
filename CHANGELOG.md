# 更新日志

所有重要更改都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 新增
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
