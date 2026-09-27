# DownloadKit 下一阶段开发计划

> 建立：2026-09-27 ｜ 当前版本 v0.4.1
> 用法：每完成一项，把该项的 `- [ ]` 改成 `- [x]`，并在下方「进度」补一行记录。

---

## 进度

| 日期 | 完成项 | 备注 |
|------|--------|------|
| 2026-09-27 | P1-1 | 导航 7→6，「已下载+下载队列」合并为「下载」页（进行中/已完成 子 tab）；pytest 249 passed，浏览器走查 console 零错误 |
| 2026-09-27 | P1-3 | 设置页只留总目录，4 分类收进高级折叠 + 只读路径预览；顺手修了根目录 change 不同步分类的既有 bug；pytest 263 passed |
| 2026-09-27 | P1-2 | 设置页重排为 5 组卡片（下载/应用/网络/启动与后台/关于），网络组用子标题分三段；补 `.content` 缺失闭合，整份 HTML 标签首次严格配平；pytest 270 passed |
| 2026-09-27 | P1-5 | 新增解答页 `panel-help`（不占侧边栏、设置页内链进出）：目录 6 锚点 + 下载目录/Cookie/扫码登录/代理说明 + FAQ 7 条 + 报错对照 6 行；锚点改瞬时滚 `.content`；pytest 279 passed |
| 2026-09-27 | P1-4 | 备注治理：8 处生效提示统一为 `.eff` 药丸徽标（live/restart/next 三类）；Cookie 长卡与扫码登录长说明迁出设置页，改为 `data-help` 内链直达解答页；pytest 286 passed |
| 2026-09-27 | P1-6 | 控件三模式统一：`.f-label` 标签在上 / `.f-switch` 开关带说明 / `.f-row` 下拉右对齐；宽度收敛到 100% 与 160px 两档，内联宽度与内联开关样式清零；pytest 294 passed |
| 2026-09-27 | P1 整体验收 | 重打包 105.86MB → `test-exe.ps1` 6 个 API 全 200、`test-exe-tray.py` 33/33、`test-exe-douyin.py` 9/9（playwright 进包、抖音登录有效、抓 55 作品零下载）；红线三处 0/0/1 不变，无残留进程 |
| 2026-09-27 | P2-1 | 每创作者下载范围（`only_new`/`backfill_n`/`all`；`since_date` 缺时间源已确认缓做）：加列迁移、补下候选按 `task_id` 判重、N 为累计上限、增量优先吃配额；`mark_works_seen` 改冲突时补登任务号（原 `INSERT OR IGNORE` 会让补下每轮重下同一批）；卡片行内下拉+N 输入、all 前置 confirm；`tests/test_download_scope.py` 22 例，pytest 316 passed |
| 2026-09-27 | P2-2 | 定时检查双模式：`mode=interval\|daily_at` + `daily_at=HH:MM`，每天定时加 0~3 分钟抖动、退避仍优先、首轮仍 15 秒；前端「检查方式」下拉切两个 label 显隐，`bindPollerField` 加 transform；`tests/test_poller.py` +28 例，pytest 344 passed；走查零错误且全程未跑轮询 |
| 2026-09-27 | P2-3 | 手动检查策略入口：折叠区（下载开关/单轮上限/范围），默认值=原行为不落库；范围临时覆盖透传 `CheckAllRequest→run_round→check_all→check_creator→_apply_backfill`，校验抽 `validate_scope` 与卡片共用、开跑前 400 拦下；`tests/test_check_strategy.py` 20 例，pytest 364 passed |
| 2026-09-27 | P2-4 | 订阅卡片状态：加列 `last_attempt`/`last_result`（成败都更新），`last_checked` 仍只在成功时写（首查判断靠它，有命门测试锁死）；check_creator 四个成功出口 + check_all 三个 except + 单查端点写状态，中断只写被检查到的、暂停不写；卡片显示结果、失败标红、时间回落；`tests/test_card_status.py` 14 例，pytest 378 passed |
| 2026-09-27 | P2 验收 | 重打包 105.87MB → `test-exe.ps1` 6 API 全 200、`test-exe-tray.py` 33/33、`test-exe-douyin.py` 9/9；新增 `build/test-exe-backfill.py` 真实补下实测：backfill_n=2 入队 2 → 落盘 `videos` 1→3（+2 共 162MB，验收预期）→ 复查 `backfilled=0` 零重复 → 复原 only_new；两处落盘红线 0/0 不变，无残留进程 |
| 2026-09-27 | P3 验收 | pytest 全量 430 passed / 6 skipped → 重打包 105.88MB → `test-exe.ps1` 6 API 全 200、`test-exe-tray.py` 33/33、`test-exe-douyin.py` 9/9（含新托盘菜单「图标已启动」）；红线三处 0/0/3 不变，无残留进程 |
| 2026-09-27 | 用户实测修复 | 订阅「预览成功、订阅必失败」三层连环修复：① `fetch_creator(max_scrolls=0)` 空保护无条件触发挡死所有新订阅 → 保护加滚动条件，`max_scrolls=0` 只取资料不抓列表；② 短链落裸首页被当成功且缓存坏结果 → 不缓存、不重试（省限流额度）、直接转浏览器回退；③ 回退遇「验证码中间页」→ RateLimited 穿透 → server 429 明确文案（原笼统 400）；④ 预览消息 `<b>` 字面显示 → 纯文本化；`test_subscribe_profile_only.py` 5 例（真 fetch_creator 链路，替身浏览器绕过实现的教训）+ `test_resolve_sec_uid.py` +7 例，pytest 442 passed；真实验证：主页直订 200、短链 429 验证码文案、复原删除 |
| 2026-09-27 | P4-1 两个体验 Bug | Bug⑤ 选中残留：`refreshFiles` 裁剪 `selectedFiles`、空列表回位全选框+工具栏计数、单删同步移出选中集、重绘后恢复有效勾选；Bug⑥ 完成行点击无反应：完成行可点（`queue-item-done`）→ 新端点 `POST /api/open-file`（裸文件名在下载目录递归找分类子目录，遍历/越界 403 拦死、目录 400、缺失 404）打开文件 → `POST /api/queue/{id}/dismiss` 双侧清除（队列 + `_downloads`，只删一边刷新复活）、进行中任务 409 拒绝；headless 回文件路径弹窗（标题「文件位置」）；`tests/test_open_file.py` 17 例，pytest 458 passed |
| 2026-09-27 | P4-2 文件命名 | 抖音改 `标题 发布日期.ext`（日期在后）：浏览器后端从页面「发布时间：…」抓日期（body 正则 + `[data-e2e*=time]` 兜底，**零额外请求**，探针实测命中），旧接口路径从 `create_time` 按 UTC+8 换算（秒/毫秒/坏值都容错）；缺日期或缺标题回落 `douyin_<作品ID>` 不硬造；四命名点（浏览器视频/旧接口视频/实况/图文）统一走 `build_download_base`（非法字符清洗 + 120 字封顶），各点加 `_existing_target` 旧命名兜底去重，切换命名后重下不出第二份；`download_content` 先定死 `rename_strategy` 再做已存在预检；真实解析实测 `publish_date='2026-09-24'`、文件名 `…2026-09-24.mp4`；`tests/test_douyin_naming.py` 18 例，pytest 477 passed |
| 2026-09-27 | P4-3 UI 统一 | 5 个真开关改 `.switch` 平移 toggle（appearance:none + `::after` 滑块，原生 checkbox/`label[for]` 保留，JS 零改动）；代理三态 radio 改 `.segmented` 分段按钮（radio 视觉隐藏留 DOM，`test_proxy`/`test_control_modes` 结构断言零改动全兼容）；`.search-input` 统一带边框盒（`.search-box` 内清透明防双边框）+ `.compact` 紧凑档收编订阅面板内联；`.btn-xs`/`.btn [data-lucide] 15px` 收编 16 处内联，📂🌐🔍→lucide；订阅「自动检查」两句并一句；走查 7 面板 console 零错误 + 截图核对（误点启用跑了 1 轮空轮询，0 下载已恢复关闭）；pytest 477 passed / 6 skipped |
| 2026-09-27 | P4-4 confirm 弹窗 + 内联收编 | 原生 `confirm` 全换 `uiConfirm`（utils.js 返回 Promise，Enter/Esc/遮罩/焦点陷阱，textContent 防注入、不用 id），13 处调用方 async 化、文案不动；两处测试断言 `confirm(`→`uiConfirm(`；新增 `.row`/`.card`/`.card-title` 收编 11 处内联，JS 模板 10 处图标内联尺寸清零；修 settings.js 8 处不存在的 `var(--danger)`（红字失效）→ `var(--error)`；走查四路径 + 订阅范围取消回滚 API 零写入 console 零错误；pytest 477 passed / 6 skipped |
| 2026-09-27 | P4 整体验收 | 重打包 105.89MB → `test-exe.ps1` 6 API 全响应、`test-exe-tray.py` 33/33、`test-exe-douyin.py` 9/9（首次 7/8 系脚本硬编码旧 sec_uid 撞退订 404，改用实时订阅列表后全过，非 P4 回归）；红线三处 0/0/0 与打包前一致（videos 基线因用户手删从 3→0），无残留进程 |
| 2026-09-27 | Bug 修复：设置页 422 | 用户实测「选择目录/打开」报「Input should be a valid dictionary」；curl 四组对照定位：`api()` 只给对象 body 设 `Content-Type`，settings.js 6 处自行 stringify 成字符串 → fetch 发 `text/plain` → 9-26 升级的 fastapi 0.141.1 不解析非 JSON body → Pydantic 422（老版不看 header 所以旧版没炸；`test-exe.ps1` 自带 header 所以验收没拦住）；修 6 处传对象 + `api()` 加 string body 兜底 + 新增 `test_api_content_type.py` 3 例（pytest 480 passed）+ 验收脚本补 open-dir 3f；浏览器实测两按钮通过，重打包 105.89MB → 三套验收全绿（6 API 含 3f / 33/33 / 9/9），红线 0/0/0 |
| 2026-09-27 | 依赖对齐 | `backend/requirements.txt` 7 项钉死版本对齐 .venv 实际安装（fastapi 0.115.0→0.141.1、uvicorn 0.30.0→0.54.0、httpx 0.27.0→0.28.1、pydantic 2.9.0→2.13.5、yt-dlp 2024.8.0→2026.8.19、mutagen 1.47.0→1.48.1、python-dotenv 1.0.1→1.2.3），起因是上一条 422 事故里 fastapi 两处版本不一致；逐项核对 requires-python 均 ≥3.10 兼容 NAS Dockerfile 的 python:3.11-slim，8 项 NAS 版专用项（sqlalchemy/celery/redis 等，.venv 未装）原样保留 |

---

## P1 界面整理（先做，一次动完 UI 避免返工）

- [x] **P1-1 导航 7→6：合并「已下载 + 下载队列」**（2026-09-27 完成）
  - 合并为「下载」页，页内顶部子 tab：`进行中 ｜ 已完成`，两套原有交互原样保留
  - 风险：`queue.js` / `files.js` 的初始化与轮询生命周期要跟着挪，防止「切 tab 后不再刷新」
  - 验收：两面板轮询启停有回归用例；`tests/test_static_refs.py` 通过
  - 文件：`downloadkit/static/index.html`、`js/queue.js`、`js/files.js`

- [x] **P1-2 设置页重排为 5 组**（2026-09-27 完成，先于备注治理做，同一批 HTML 不返工）
  - 应用（并发/日志/历史）· 下载（总目录/重名/实况照片）· 网络（代理+登录/Cookie，组内子标题分三段）· 启动与后台 · 关于（版本号）
  - 关于页版本号与 `pyproject.toml` 由测试钉死，发版忘改会红
  - 附带修复：补上 `.content` 一直缺失的 `</div>`（原文件靠浏览器容错兜着），整份 HTML 标签首次严格配平
  - 文件：`downloadkit/static/index.html`、`css/main.css`

- [x] **P1-3 下载目录只留总目录**（2026-09-27 完成，先于 P1-2 做，同一批 HTML 不返工）
  - 只保留总目录输入框；4 个分类改成只读展示「将存入 …/music、…/videos」，「高级」折叠里才单独改
  - 后端 5 个字段全保留，兼容已有配置（v0.4.1 已做的联动逻辑继续生效）
  - 附带修复：根目录 change 监听原本闭包捕获 `lastRoot`（初始化时是空串），
    `loadSettings` 异步填值后不同步，导致首次改根目录分类不跟着走 → 改为模块级 `lastDirRoot`
  - 文件：`downloadkit/static/index.html`、`js/settings.js`、`css/main.css`

- [x] **P1-4 备注治理**（2026-09-27 完成，长文迁去 P1-5 建好的解答页）
  - `立即生效 / 需重启 / 下次启动生效` 统一为一种小徽标 `.eff`（+ `eff-live/restart/next` 三个语义类）
  - Cookie 长卡、扫码登录长说明整体迁出设置页，原位置留一句话 + `data-help` 内链（点击直达解答页对应锚点）
  - 文件：`downloadkit/static/index.html`、`css/main.css`

- [x] **P1-5 新增「解答」页**（2026-09-27 完成；先建页，P1-4 才往里迁长文）
  - 新建 `panel-help`：**不占侧边栏导航**，从设置页内链进入，带返回（回进来的那个页面）
  - 收纳长说明 + FAQ 7 条 + 报错对照 6 行；左侧目录 6 锚点
  - 两个坑已在测试里锁死：`app.js` 必须透出 `__switchTab`/`__closeSidebar`（否则进得来回不去）；
    锚点必须 `behavior:'auto'` 且滚 `.content`（`.main` 是 overflow:hidden，smooth 动画不跑等于没反应）
  - 文件：新增 `downloadkit/static/js/help.js`、`index.html`、`css/main.css`、`js/app.js`、`js/utils.js`

- [x] **P1-6 控件样式统一**（2026-09-27 完成）
  - 只留三种模式：标签在上 `.f-label` / 开关带一句说明 `.f-switch` + `.f-hint` / 下拉右对齐 `.f-row`
  - 间距与宽度统一：宽度只有 `100%` 与 `160px` 两档，内联 width 与内联开关样式在设置页清零
  - 范围限定设置页；订阅页卡片头的行内下拉（句中嵌入）保持原样
  - 文件：`downloadkit/static/index.html`、`css/main.css`

**P1 验收**（2026-09-27 全部通过）：视觉走查 ✓ → `pytest` 全量 294 passed / 6 skipped ✓ → `build\build-release.ps1` 重打包 105.86MB ✓ → 三项 exe 实测（`test-exe.ps1` 6 个 API 全 200、`test-exe-tray.py` **33/33**、`test-exe-douyin.py` **9/9**）✓ → 红线三处文件数 0 / 0 / 1 与打包前一致 ✓ → 分次提交 ✓

---

## P2 订阅功能（核心）

- [x] **P2-1 每创作者下载范围**（2026-09-27 完成）
  - `creators` 加列 `download_scope` + `scope_param`（走已有 `ALTER TABLE` 迁移先例）
  - 取值：`only_new`（默认，现状）/ `backfill_n`（往回补 N 个）/ `all`（全部补下）
    - `since_date`（从某日期起）**本期缓做**：抖音主页只给作品 ID 不给发布时间，
      没有可靠时间源，硬做只能逐个开详情页读 `create_time`，慢且易触发风控（已与用户确认）
  - `check_creator()` 按范围算基线起点，**水位线防重复逻辑不动**；
    补下候选 = 水位线之下且 `task_id` 为空，入队成功才补登 `task_id`
    （`mark_works_seen` 由 `INSERT OR IGNORE` 改为冲突时更新，否则任务号永远写不进去，
    每轮都会把同一批重下一遍）
  - `backfill_n` 的 N 是**累计上限**，不是每轮上限（`count_backfilled` 按水位线过滤）
  - 配额：`max_new` 先给增量，余量才给补下（`_budget`：`-1`=不限，`0`=没余量，混用会塞爆队列）
  - 卡片行内控件：范围下拉 + 条件出现的 N 输入框，`all` 前置 confirm，失败按服务端真值重画
  - 测试：`tests/test_download_scope.py` 22 例（含反复检查不重复入队、增量优先、探针零入队、迁移幂等）
  - 文件：`downloadkit/subscription.py`、`subscription_service.py`、`server.py`、`js/subscriptions.js`、`css/main.css`

- [x] **P2-2 定时检查双模式**（2026-09-27 完成）
  - `mode = interval | daily_at` + `daily_at="09:00"`，状态区显示「下次检查 14:30」
  - 保留现有间隔模式与风控指数退避：退避优先级高于每天定时（只抬基础等待）
  - daily_at 等到下一个时刻再加 0~3 分钟随机抖动（固定到秒敲也是固定节律）；
    今天已过等明天；首轮仍 15 秒（打开开关马上见效，之后才进入每天节律）
  - 配置校验静默修正（`_valid_daily_at`），回读显示实际生效值
  - 前端：「检查方式」下拉切换「检查间隔 / 每天时刻(time)」两个 label 显隐，
    `bindPollerField` 加 `transform` 参数（mode/daily_at 是字符串，原来写死 `parseInt`）
  - 测试：`tests/test_poller.py` 新增 28 例（取值校验、跨天翻转、抖动、首轮、退避优先、界面结构）
  - 文件：`downloadkit/poller.py`、`server.py`、`index.html`、`js/subscriptions.js`

- [x] **P2-3 下载策略入口**（2026-09-27 完成）
  - 「检查全部更新」上方加折叠策略区：下载开关 / 单轮上限 / 下载范围
  - 默认值 = 改造前行为（下载、单轮 1 个、跟随各创作者设置），**不落库**，
    每次点检查现读现用；范围选 `all` 与卡片同样前置 confirm
  - 范围临时覆盖走完整链路：`CheckAllRequest` → `run_round` → `check_all`
    → `check_creator` → `_apply_backfill`，全程只影响本轮，绝不写 `creators`
  - 校验在开跑前拦（`validate_scope` 与卡片 `set_creator_scope` 同一函数，
    非法值 400 中文报错，不等抓完主页才发现策略写错）
  - 结果行区分「新作品入队」与「补下历史 N 个（还剩 M）」
  - 测试：`tests/test_check_strategy.py` 20 例（不落库、开跑前拦截、
    两层透传、策略受配额约束、界面默认值锁死）
  - 文件：`server.py`、`downloadkit/poller.py`、`subscription.py`、
    `subscription_service.py`、`index.html`、`js/subscriptions.js`

- [x] **P2-4 订阅卡片状态**（2026-09-27 完成）
  - 加列 `last_attempt`（成败都更新）+ `last_result`（中文摘要/失败原因）；
    **`last_checked` 保持只在成功时更新** —— 首查判断 `if not last_checked`
    靠它，失败也写会让「首查失败」被当成已建基线，水位线判断跑偏（有命门测试）
  - 写入点：`check_creator` 四个成功出口（基线/补建水位线/探针/常规）、
    `check_all` 三个 except（风控/未登录/单个异常，中断时**只写被检查到的**）、
    单查端点四个 except；暂停（skipped）不写状态
  - 卡片元信息行显示「上次检查 X 分钟前 + 结果」，失败按「失败：」前缀标红，
    时间列空时回落 `last_checked`（老订阅不显示成「还没检查过」）
  - 测试：`tests/test_card_status.py` 14 例（含命门：首查失败后 `last_checked`
    仍空、第二次成功仍走建基线分支）
  - 文件：`downloadkit/subscription.py`、`subscription_service.py`、`server.py`、`js/subscriptions.js`

**P2 验收**（2026-09-27 通过）：新增回归测试（范围三种模式 × 水位线不重复）→ `pytest` 全量
**378 passed / 6 skipped** → 重打包 **105.87MB** → `test-exe.ps1` 6 API 全 200、
`test-exe-tray.py` 33/33、`test-exe-douyin.py` 9/9 → **真实创作者实测补下 2 个**
（`build/test-exe-backfill.py`：笔吧评测室 backfill_n=2 → 入队 2 → 真实落盘
`videos` 1→3 → 复查 `backfilled=0` 零重复、文件数不变 → 范围复原 only_new）。
红线：两处落盘 0/0 不变，`videos` +2 是验收预期；无残留进程

---

## P3 代理与打磨

- [x] **P3-1 代理三态 + 按平台覆盖 + 测试连接**（2026-09-27）
  - `关闭 / 跟随系统 / 手动` 单选；平台覆盖：YouTube / B站 / 抖音 / 小红书
  - 新端点 `POST /api/proxy/test`，回延迟与可用性
  - 文件：`downloadkit/proxy.py`、`server.py`、`index.html`、`js/settings.js`
  - 旧配置兼容：`resolve_mode` 按「不改现有行为」推导 —— `enabled=false`→off、有地址→manual、全空→system（老 youtube 实际走系统代理）；off 是硬关闭，填过的地址不许悄悄生效
  - `youtube.py` 两处补传 `load_config()`（此前不传配置，三态对它无效）
  - `settings/get` 附带 `proxy_system` 回显系统代理探测值；`/api/proxy/test` 永远 200、可用性放 `body.ok`，超时/连不上给中文分类提示（连不上代理 vs 网络不通）
  - 前端：三态 radio + 手动态才可编辑地址框 + 跟随系统回显 + 测试按钮；`tests/test_proxy.py` 22 例；pytest 400 passed

- [x] **P3-2 队列打磨**：一键重试全部失败、进度保留（2026-09-27）
  - `retry_task` 不再清 `progress`/`downloaded_size`：downloader 按文件已有字节断点续传，重试是接着下，清零只会让进度条在重试瞬间倒退；`error` 照清
  - 新端点 `POST /api/queue/retry-failed`：只重试队列里真实存在的 FAILED；`_downloads` 孤儿 failed 卡（实体已被 cleanup 清掉）如实统计成 `orphaned` 上报 —— 视频条目不存原链接、音乐条目 url 是 song_id 走视频接口必然再失败，硬发只会批量制造新失败任务
  - 队列头部加「N 失败」统计与「重试全部失败」按钮（无失败即隐藏）；toast 把 retried/orphaned 转述清楚
  - `tests/test_queue_polish.py` 8 例；走查注入 FAILED 实体 + 孤儿卡全链路验证（组合/孤儿 toast、62% 进度跨重试保留、单任务 400 回归、空队列隐藏），console 零错误

- [x] **P3-3 其他候选**（2026-09-27，分四次提交）：设置导出导入、托盘菜单快捷项、解答页搜索、音乐/资源页下载按钮状态统一
  - **解答页搜索**：页头 type=search 输入框，两级过滤（块级标题命中整块恢复 + 行级 li/表格行/dt+dd 成对/独立段落），目录与空状态联动，进入重置；`test_help_panel.py` +3 例
  - **设置导出导入**：footer 加导出/导入按钮；导出现拉配置落带日期 JSON（general/proxy/cookie/subscription 四段，cookie 是路径不带登录态）；导入段级白名单 + confirm + 写完刷新，坏 JSON/无识别段中文报错；`test_settings_io.py` 4 例
  - **按钮状态统一**：`downloadResource` 收 btn 参数（内联按钮状态落自己，修掉主按钮不在 DOM 时的 null 崩），完成/失败态保留不 2 秒抹回，两页三态文案一致（下载中…/已下载/下载失败），音乐页补「下载中」title；`test_button_states.py` 8 例
  - **托盘快捷项**：菜单加「打开下载目录」「检查订阅更新」+ 分隔；两个动作抽 run.py 顶层函数（open_download_dir / check_subscription_update）便于单测 mock，检查动作起 daemon 线程不卡托盘 UI，气泡通知转后端 message；`test_tray_menu.py` 7 例（含 pystray 实际构造菜单）；点击无法自动化，构造与接线靠单测 + exe 日志断言覆盖

**P3 验收**（2026-09-27 全部通过）：`pytest` 全量 **430 passed / 6 skipped** ✓ → `build\build-release.ps1` 重打包 105.88MB ✓ → 三项 exe 实测（`test-exe.ps1` 6 个 API 全 200、`test-exe-tray.py` **33/33**、`test-exe-douyin.py` **9/9**）✓ → 红线三处 0/0/3 与打包前一致、无残留进程 ✓ → 提交 ✓

---

## P4 体验优化（2026-09-27 用户实测提出，按四批走）

用户拍板结论：命名日期用**视频发布日期**（要多抓一个字段）；格式 **`标题 2026-09-27.mp4`**（日期在后）；
完成行**点行直接打开文件并自动移出「进行中」**；订阅备注**删到只剩一句**；真开关改 toggle、
代理三态改分段按钮（全选/文件行复选框保留）；按下面四批顺序执行。

- [x] **P4-1 两个交互 Bug**（2026-09-27 完成）
  - Bug⑤「删除选中 (N)」计数残留：`files.js` 的 `refreshFiles` 刷新后裁剪 `selectedFiles`（只留仍存在的）、
    空列表分支回位全选框与工具栏、单删成功同步 `delete selectedFiles[path]`、重绘后恢复仍有效勾选并同步全选框半选态
  - Bug⑥ 已完成项点击无反应：完成行加 `queue-item-done`（cursor:pointer + 悬停提示），点击 →
    `POST /api/open-file`（`_resolve_open_file`：先走 `safe_download_path` 安全校验，404 再按裸文件名在下载目录
    递归找分类子目录里的文件；遍历/越界 403、目录 400、缺失 404）→ 成功后 `POST /api/queue/{id}/dismiss`
    把任务从 `download_queue.active_tasks` 与 `_downloads` **双侧**移除（只删一边 queue/status 会拼回来）；
    进行中（pending/downloading/paused）409 拒绝；headless 返回文件 NAS 路径弹窗
  - 文件：`server.py`、`downloadkit/download_queue.py`（`dismiss_task`）、`js/files.js`、`js/queue.js`、`css/main.css`
  - 测试：`tests/test_open_file.py` 17 例（安全解析 7 + 端点 2 + dismiss 5 + 前端接线 3），pytest 458 passed

- [x] **P4-2 文件命名：抖音按「标题 发布日期」**（格式 `标题 2026-09-27.mp4`，2026-09-27 完成）
  - 发布日期取详情接口的 `create_time`（已确认多抓一个字段）；取不到时回落现有 `douyin_<作品ID>` 命名，不硬造
  - 实际取值点（探针实测后定）：**浏览器后端（主路径）从页面 DOM 抓「发布时间：2026-09-24 16:59」**
    （body 正则 + `[data-e2e*="time"]` 兜底，零额外请求零风控），旧接口路径从 `create_time` 按 UTC+8 换算
  - 改造点：`douyin.py` 视频/动图图片命名与已存在检测；`server.py` 历史 title 提取**验证兼容无需改**
    （旧 `douyin_\d+_` 前缀正则对新名是 no-op，`_motion_` 替换照常生效）；旧文件不批量重命名，
    但新命名下载前用 `_existing_target` 兜底查旧命名文件（切命名后重下不出第二份）；
    订阅增量判定走 aweme_id 水位线，与文件名无关
  - 测试：`tests/test_douyin_naming.py` 18 例；真实解析实测 `publish_date='2026-09-24'`、
    文件名 `手搓游戏本…长长见识， 2026-09-24.mp4`
  - 文件：`downloadkit/douyin.py`、`downloadkit/douyin_browser.py`

- [x] **P4-3 UI 统一：组件样式 → toggle 开关 → 备注收敛**（2026-09-27 完成）
  - **toggle 开关**：5 个真开关（订阅启用、检查策略下载、实况照片、开机自启、关闭到托盘）改左右平移
    `input[type=checkbox].switch`（appearance:none + `::after` 滑块，原生 checkbox 与 `label[for]` 保留，
    JS 与 `.f-switch` 结构零改动）；全选与文件行复选框保留 checkbox 语义不动
  - **代理三态 → 分段按钮**：`.segmented` + `.seg-item`，radio 视觉隐藏留在 DOM（id/name/checked 断言、
    `settings.js` 的 `:checked` 读写全兼容），选中态黑底白药丸
  - **输入框统一**：`.search-input` 默认自带边框盒（原来只有大搜索盒有框，设置/订阅页全是裸文字），
    `.search-box` 内部清回透明防双边框；新增 `.search-input.compact` 紧凑档收编订阅面板下拉/时间/N 输入
    与 Cookie 浏览器选择的内联样式
  - **按钮 token**：`.btn-xs` 收编 12 处内联 padding；`.btn [data-lucide]` 统一 15px 替掉 4 处内联图标尺寸；
    emoji 按钮换 lucide（📂→folder-open、🌐→globe、🔍→search、←→arrow-left），FAQ 同步改词
  - 订阅「自动检查」两条备注**合并成一句**（间隔与验证码说明都保留在句内）
  - 文件：`index.html`、`css/main.css`、`js/collections.js`（coll-add-url 内联盒样式收编），版本 `20260927k`；
    `settings.js` 零改动
  - 测试：既有结构断言（`test_proxy` 三态、`test_control_modes` 三模式）因保留原生 input **零测试改动**，
    pytest 477 passed / 6 skipped；浏览器走查 7 面板 console 零错误 + 截图核对
  - 备注：走查时误点订阅「启用」触发 1 轮空轮询（访问 1 个创作者页），队列 0 任务、下载目录 0 文件，
    已立即关闭并恢复 `enabled=false`

- [x] **P4-4 可选打磨**：自定义 confirm modal（替原生 `confirm`）、行内 style 收编进 class（2026-09-27 完成）
  - **`uiConfirm(message, options)`**（utils.js）：返回 Promise，Enter=确认 / Esc=取消 / 点遮罩=取消、
    焦点关在弹窗内 Tab 来回；正文用 `textContent` + `white-space:pre-line`（`\n` 换行、尖括号不被当 HTML 解析）；
    全程不用 id（静态引用检查只认 index.html 里存在的元素），样式 `.ui-modal-*` 挂 main.css 文末
  - 13 处原生 `confirm` 全部转换（files/queue/subscriptions/settings/collections/douyin-login），
    调用方函数改 `async` + `await uiConfirm(...)`；消息文案一字未动
  - 测试同步：`test_queue_polish`/`test_settings_io` 的 `"confirm("` 断言改 `"uiConfirm("`（确认意图不变）
  - 行内收编：新增 `.row`（5+2 处 flex 行）、`.card`（2 张订阅卡壳）、`.card-title`（2 处）；
    JS 模板里 10 处 `width:14px;height:14px` 图标内联全清（settings 1 + collections 3 + resource 6，
    由 `.btn [data-lucide]` 接管）
  - 顺手修 settings.js 8 处 `var(--danger)` → `var(--error)`：`--danger` token 不存在，
    这些错误状态的红字一直在渲染成继承色
  - 走查：Esc/Enter/确认钮/遮罩四路径全对；真实业务路径（订阅范围改「全部补下」→ 取消）回滚到
    `only_new` 且 API 零写入；console 零错误；pytest 477 passed / 6 skipped
  - 版本 bump：utils/main.css/settings/subscriptions/files/queue/collections/resource/douyin-login → `20260927l`

**P4 验收**（2026-09-27 全部通过）：四批全勾（P4-1 `2ca7802` → P4-2 `fb99388` → P4-3 `c4a0660` → P4-4 `ccd5a75`）✓ →
`pytest` 全量 **477 passed / 6 skipped** ✓ → `build\build-release.ps1` 重打包 **105.89MB** ✓ →
三项 exe 实测（`test-exe.ps1` 6 个 API 全响应、`test-exe-tray.py` **33/33**、`test-exe-douyin.py` **9/9**：
首次 7/8 是脚本硬编码旧 sec_uid 撞上退订 404，已改为用 [2] 步实时订阅列表取值，属脚本缺陷非 P4 回归）✓ →
红线三处 **0/0/0** 与打包前基线一致（用户手删过 videos，基线从 P3 的 0/0/3 变 0/0/0，以本次为准）✓ →
无残留进程（8765 仅 TIME_WAIT）✓ → 分次提交 ✓

---

## 全局验收（每期结束固定跑）

1. `$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest tests -q`
2. `powershell -File build\build-release.ps1` 重打包
3. `build\test-exe.ps1`、`build\test-exe-tray.py`（33 项）、`build\test-exe-douyin.py`（9 项）
4. 红线：`downloads/`、`dist/downloads/`、`~/Downloads/DownloadKit/videos` 文件数不变
5. 改动落盘后提交（中文提交信息走 `-F` 文件，避免编码损坏）
