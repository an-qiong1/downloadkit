"""downloadkit 包导入时的 no_proxy 净化（2026-10-17 打包版启动崩溃回归）

根因链：Windows 系统代理约定里常见的 no_proxy 写法含 ``[::1]``
（带方括号的 IPv6 字面量）→ httpx 0.28 构造 Client 时把它按
``host:port`` 切分（host=``:``, port=``1]``）→ 抛
``InvalidURL: Invalid port: ':1]'`` → ``platforms/netease.py`` 在
**模块级**构造 AsyncClient → **导入 downloadkit 包即炸**。

打包版表现：双击 exe 弹「DownloadKit - 启动失败」对话框，
整个应用起不来（2026-10-17 实测复现，崩在
netease.py:91 → httpx 的 URLPattern 解析）。

修复：``downloadkit/__init__.py`` 在包导入最前面剥掉方括号
（``[::1]`` → ``::1``，同一地址、语义等价）。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run_python(code: str, env_no_proxy: str) -> tuple[int, str]:
    """在独立子进程里以指定 no_proxy 执行 code（避免污染本测试进程）。"""
    import os
    env = dict(os.environ)
    env["no_proxy"] = env_no_proxy
    env["NO_PROXY"] = env_no_proxy
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, cwd=str(ROOT), timeout=60,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def test_import_package_strips_bracketed_ipv6():
    """导入 downloadkit 包后，no_proxy 里不许残留方括号条目"""
    code = (
        "import os; import downloadkit; "
        "print(os.environ['no_proxy'])"
    )
    rc, out = _run_python(code, "localhost,127.0.0.1,::1,[::1]")
    assert rc == 0, out
    value = out.strip().splitlines()[-1]
    assert "[" not in value and "]" not in value, (
        f"方括号没被剥掉：{value!r} —— netease.py 模块级 AsyncClient 会炸"
    )
    # 其余条目必须原样保留（只动方括号项）
    assert "localhost" in value and "127.0.0.1" in value


def test_import_package_allows_httpx_client_construction():
    """带 [::1] 的环境里导入包后，httpx 裸构造 AsyncClient 必须成功"""
    code = (
        "import asyncio, downloadkit, httpx\n"
        "async def m():\n"
        "    c = httpx.AsyncClient()\n"
        "    await c.aclose()\n"
        "    print('OK')\n"
        "asyncio.run(m())\n"
    )
    rc, out = _run_python(code, "localhost,127.0.0.1,::1,[::1]")
    assert rc == 0, out
    assert "OK" in out, out


def test_sanitizer_leaves_clean_values_untouched():
    """干净值不许被改动（避免破坏用户/代理客户端的既有配置）"""
    from downloadkit import _sanitize_no_proxy_env
    import os

    original = os.environ.get("no_proxy")
    try:
        for clean in ("localhost,127.0.0.1,::1", "*.example.com,localhost",
                      "", "localhost"):
            os.environ["no_proxy"] = clean
            _sanitize_no_proxy_env()
            assert os.environ["no_proxy"] == clean, \
                f"干净值被改动了：{clean!r} -> {os.environ['no_proxy']!r}"
    finally:
        if original is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = original


def test_sanitizer_handles_spacing_and_mixed():
    """带空格、混合条目也要正确处理"""
    from downloadkit import _sanitize_no_proxy_env
    import os

    original = os.environ.get("no_proxy")
    try:
        os.environ["no_proxy"] = "localhost, [::1] ,127.0.0.1"
        _sanitize_no_proxy_env()
        assert os.environ["no_proxy"] == "localhost,::1,127.0.0.1", \
            os.environ["no_proxy"]
    finally:
        if original is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = original
