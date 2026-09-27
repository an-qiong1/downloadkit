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

- [ ] **P2-2 定时检查双模式**
  - `mode = interval | daily_at` + `daily_at="09:00"`，状态区显示「下次检查 14:30」
  - 保留现有间隔模式与风控指数退避
  - 文件：`downloadkit/poller.py`、`index.html`、`js/subscriptions.js`

- [ ] **P2-3 下载策略入口**
  - 手动「检查全部更新」前可选：下载开关 / 单轮上限 / 范围
  - 文件：`js/subscriptions.js`、`index.html`

- [ ] **P2-4 订阅卡片状态**
  - 显示上次检查时间 + 结果或中文失败原因
  - 文件：`js/subscriptions.js`

**P2 验收**：新增回归测试（范围三种模式 × 水位线不重复）→ `pytest` 全量 → 重打包 → 真实创作者实测补下 N 个

---

## P3 代理与打磨

- [ ] **P3-1 代理三态 + 按平台覆盖 + 测试连接**
  - `关闭 / 跟随系统 / 手动` 单选；平台覆盖：YouTube / B站 / 抖音 / 小红书
  - 新端点 `POST /api/proxy/test`，回延迟与可用性
  - 文件：`downloadkit/proxy.py`、`server.py`、`index.html`、`js/settings.js`

- [ ] **P3-2 队列打磨**：一键重试全部失败、进度保留

- [ ] **P3-3 其他候选**：设置导出导入、托盘菜单快捷项、解答页搜索、音乐/资源页下载按钮状态统一

**P3 验收**：`pytest` 全量 → 重打包 → 三项 exe 实测 → 红线核对（三处落盘目录文件数不变）

---

## 全局验收（每期结束固定跑）

1. `$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest tests -q`
2. `powershell -File build\build-release.ps1` 重打包
3. `build\test-exe.ps1`、`build\test-exe-tray.py`（33 项）、`build\test-exe-douyin.py`（9 项）
4. 红线：`downloads/`、`dist/downloads/`、`~/Downloads/DownloadKit/videos` 文件数不变
5. 改动落盘后提交（中文提交信息走 `-F` 文件，避免编码损坏）
