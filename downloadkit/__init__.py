"""downloadkit 包初始化。

no_proxy 健壮性净化（2026-10-17 打包版启动崩溃回归）
----------------------------------------------------
httpx 0.28 构造 Client 时会解析环境里的 no_proxy，把每一项按
``host[:port]`` 处理；而 Windows 系统代理约定里常见的 ``[::1]``
（带方括号的 IPv6 字面量）会被切成 host=``:``、port=``1]``，直接抛
``InvalidURL: Invalid port: ':1]'``。

炸点不在业务代码：``platforms/netease.py`` 在**模块级**构造
AsyncClient，于是任何带此类 no_proxy 值的环境里，导入 downloadkit
包即失败 —— 打包版表现为双击 exe 弹「启动失败」对话框，整个应用
起不来。

这里在包导入的最前面把方括号剥掉（``[::1]`` → ``::1``，同一地址，
语义等价），兼容任何注入方（代理客户端 / 终端工具 / CI）。
"""

import os


def _sanitize_no_proxy_env() -> None:
    """就地净化 no_proxy / NO_PROXY 里带方括号的条目。

    只动方括号包裹的项（IPv6 字面量的合法写法），其余原样保留；
    值里没有 ``[`` 就完全不碰（零开销、零副作用）。
    """
    for key in ("no_proxy", "NO_PROXY"):
        raw = os.environ.get(key)
        if not raw or "[" not in raw:
            continue
        parts = []
        for p in raw.split(","):
            p = p.strip()
            if p.startswith("[") and p.endswith("]"):
                p = p[1:-1]
            if p:
                parts.append(p)
        os.environ[key] = ",".join(parts)


_sanitize_no_proxy_env()
