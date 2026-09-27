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

- [ ] **P1-4 备注治理**
  - `立即生效 / 需重启 / 下次启动生效` 统一为一种小徽标
  - 长文（Cookie 格式、扫码登录说明、报错解释）整体迁出设置页
  - 文件：`downloadkit/static/index.html`

- [ ] **P1-5 新增「解答」页**
  - 新建 `panel-help`：**不占侧边栏导航**，从设置页内链进入，带返回
  - 收纳长说明 + FAQ + 错误原因对照
  - 文件：新增 `downloadkit/static/js/help.js`、`index.html`

- [ ] **P1-6 控件样式统一**
  - 只留三种模式：标签在上 / 开关带一句说明 / 下拉右对齐；统一间距与宽度
  - 文件：`downloadkit/static/index.html`、`css/main.css`

**P1 验收**：视觉走查 → `pytest` 全量 → `build\build-release.ps1` 重打包 → 三项 exe 实测 → 分次提交

---

## P2 订阅功能（核心）

- [ ] **P2-1 每创作者下载范围**
  - `creators` 加列 `download_scope`（走已有 `ALTER TABLE` 迁移先例）
  - 取值：`only_new`（默认，现状）/ `backfill_n`（往回补 N 个）/ `since_date`（从某日期起）/ `all`（全部补下）
  - `check_creator()` 按范围算基线起点，**水位线防重复逻辑不动**
  - 必须补测试证明：同一创作者反复检查不会重复下载（订阅功能的命门）
  - 文件：`downloadkit/subscription.py`、`subscription_service.py`、`js/subscriptions.js`、`index.html`

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

**P2 验收**：新增回归测试（范围四种模式 × 水位线不重复）→ `pytest` 全量 → 重打包 → 真实创作者实测补下 N 个

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
