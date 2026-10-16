# DownloadKit CLI 退出码约定

> 建立：2026-10-16 ｜ 版本：v0.6.0

所有 CLI 命令遵循统一规则：**exit 0 = 成功（含查到空结果）；exit 2 = 用法错误**。
探测器组额外使用 **exit 1** 表示「没拿到结果」。

---

## 一、分组规则

### exit 0 — 成功 / 业务结果 / 无法操作

| 组 | 命令 | 说明 |
|----|------|------|
| **状态查询** | `queue list` / `subscribe list` / `files ls` / `collections list` / `history list` | 查到空列表不算失败，exit 0 |
| **数据管理** | `collections add` / `collections rm` / `history clear` / `history rm` | 歌单不存在 / 记录不存在是业务结果，提示后 exit 0 |
| **纯展示** | `settings get` / `settings set` / `history count` | 配置读取/写入，exit 0 |
| **解析** | `parse` / `playlist` / `download` / `douyin` | 解析成功（无论能否下载）exit 0；链接非法提示后 exit 0 |
| **搜索** | `search` | 没找到歌曲提示后 exit 0 |

### exit 1 — 探测器「没拿到结果」

| 组 | 命令 | 说明 |
|----|------|------|
| **嗅探** | `sniff` | 没抓到流 → exit 1；连不上服务 → exit 1 |
| **探测** | `bookmarks probe` | 书签无 HTTP 链接 / 启动失败 → exit 1；连不上服务 → exit 1 |
| **代理测试** | `settings proxy-test` | 代理不通 / 直连超时 → exit 1 |

> 探测器组的特点是「没抓到东西」本身就是有价值的结论，用户脚本可以靠
> exit code 判断是否需要重试或告警，所以不用 0 伪装成功。

### exit 2 — 用法错误

| 触发条件 | 示例 |
|---------|------|
| 缺必要参数 | `downloadkit history rm`（没给 ID） |
| 参数格式错误 | `downloadkit collections rm abc`（ID 不是整数） |
| 命令缺失子命令 | `downloadkit history`（没跟 list/search/rm…） |
| 选项值非法 | `downloadkit settings set general.max_concurrent -1` |

exit 2 由 Click 框架自动处理（`click.UsageError`），错误文案写 stderr，
stdout 保持干净。

---

## 二、快速对照表

```
exit 0  → 一切正常 / 业务失败（歌单不存在、记录不存在、空列表）
exit 1  → 探测器没拿到结果（sniff 无流、probe 无链接、proxy 不通）
exit 2  → 用法错误（缺参数、格式错、子命令缺失）
```

---

## 三、测试中的验证点

各测试文件里有对应断言，改动退出码逻辑时优先跑这些：

- `tests/test_cli_sniff.py` — exit 1 / exit 2
- `tests/test_cli_bookmarks_probe.py` — exit 1
- `tests/test_cli_settings.py` — proxy-test exit 1 / 用法错误 exit 2
- `tests/test_cli_history.py` — 空结果 exit 0 / 用法错误 exit 2
- `tests/test_cli_collections.py` — 业务失败 exit 0 / 用法错误 exit 2
- `tests/test_cli_douyin.py` — 解析失败 exit 0

---

## 四、与 server 端 HTTP 状态码的对应

CLI 的 exit code 与 server 端的 HTTP 状态码有明确映射关系：

| CLI exit | 触发原因 | 对应 server HTTP |
|----------|---------|-----------------|
| 0 | 成功 / 业务结果 | 200 |
| 0 | 连不上服务（给用户提示） | 连接异常 |
| 1 | 探测器无结果 | 200（body.ok=false）或 4xx/5xx |
| 2 | 用法错误 | 不走 HTTP，本地 Click 拒绝 |

> 探测器组的 exit 1 是在 CLI 层根据服务端 body 内容决定的，
> 不是服务端直接返回的 HTTP 错误码。
