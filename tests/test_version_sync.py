#!/usr/bin/env python3
"""版本号横向同步：所有「当前版本」声明必须等于 pyproject.toml

根因（2026-10-14 盘点）：版本号散在 4 个文件里手写，`downloadkit/__init__.py`
是空的没有 `__version__`，于是各自为政 —— CHANGELOG 已发到 0.5.0，
pyproject / CLI / 关于页 / 安装包却还停在 0.4.1。

关于页那处已有 test_settings_groups.py 钉死，但 CLI 的
`@click.version_option` 没人管，漏了一整版。这里一次性横向扫全，
以后再加版本点记得同步登记到 POINTS 里。

注意：只认「当前版本」的精确写法。仓里还有历史指代（如
「v0.4.1 起会自动搬迁旧目录」）是描述既往行为的，不该跟着改，
所以断言模式必须足够具体，别误伤。
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


# (相对路径, 断言正则, 该正则应命中几次)
# 命中次数写死：防止「改成了没有版本号的空写法」也能蒙混过关。
POINTS = [
    ("pyproject.toml",
     r'^version = "([^"]+)"$', 1),
    ("downloadkit/cli.py",
     r'@click\.version_option\(version="([^"]+)"', 1),
    ("downloadkit/static/index.html",
     r'id="setting-version"[^>]*>([^<]+)<', 1),
    ("build/installer/downloadkit.iss",
     r'^AppVersion=(.+)$', 1),
]


def test_all_version_points_match_pyproject():
    """4 处当前版本声明必须和 pyproject.toml 完全一致。"""
    real = _pyproject_version()
    problems = []

    for rel, pattern, want in POINTS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        found = re.findall(pattern, text, re.M)

        if len(found) != want:
            problems.append(f"{rel}: 匹配到 {len(found)} 处，期望 {want} 处"
                            f"（模式 {pattern!r} —— 是不是改了写法没更新本测试？）")
            continue

        # 关于页显示的是 v0.5.0，带 v 前缀
        shown = found[0].strip().lstrip("v")
        if shown != real:
            problems.append(f"{rel}: 写的是 {shown}，pyproject 是 {real}")

    assert not problems, "版本号不同步：\n  " + "\n  ".join(problems)


def test_historical_mentions_are_not_rewritten():
    """历史指代不该被批量替换成新版本号。

    这些句子描述的是「某个版本之前就有的行为」，版本号变了它们反而要保持原样。
    本测试锁的是「它们确实还在」，防止以后有人跑批量替换把历史说明也刷了。
    """
    html = (ROOT / "downloadkit/static/index.html").read_text(encoding="utf-8")
    assert "v0.4.1 起会把老版本散落在系统下载目录里" in html, (
        "关于页的搬迁说明描述的是 v0.4.1 引入的行为，不该跟着版本号走")
