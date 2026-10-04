# 更新日志

所有重要更改都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
