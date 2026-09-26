# -*- coding: utf-8 -*-
"""静态资源引用一致性：JS 里写死的元素 ID 必须真实存在。

为什么要有这个测试（2026-09-26 实测踩到）：
    music.js 的 downloadPlaylistSongs() 里有一行
        $('#playlist-clear-btn').style.display = 'none';
    而 #playlist-clear-btn 这个 ID 在 index.html 和任何 JS 里都不存在。
    它排在 `state.songs = songs` / `renderResults()` **之前**，所以点
    「全部下载」会立刻 TypeError，歌单批量下载整个不可用。

    这类错误的坏处是：静态读代码看不出来，源码模式下不点一次也不会暴露，
    只有真的走到那个分支才炸。所以用测试把它钉死。

覆盖面：9 个 JS 文件、约 190 处 ID 引用。
不覆盖：querySelector 里的复合选择器（`.cls` / `#a > #b`）、CSS 类名
—— 后者大量由 JS 动态拼接，误报会淹没真问题。
"""
import io
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "downloadkit", "static")
INDEX = os.path.join(STATIC, "index.html")

# 只抓「按 ID 取元素」的两种写法
REF_PATTERNS = [
    re.compile(r"""\$\(\s*['"]#([A-Za-z][\w-]*)['"]\s*\)"""),
    re.compile(r"""getElementById\(\s*['"]([A-Za-z][\w-]*)['"]\s*\)"""),
]
# 抓「定义 ID」的写法：HTML 属性、JS 字符串模板里的 id=、赋值 .id =
DEF_PATTERNS = [
    re.compile(r"""id\s*=\s*["']([\w-]+)["']"""),
    re.compile(r"""\.id\s*=\s*['"]([\w-]+)['"]"""),
]


def _js_files():
    found = []
    for dirpath, _dirs, files in os.walk(STATIC):
        for f in sorted(files):
            if f.endswith(".js"):
                found.append(os.path.join(dirpath, f))
    return sorted(found)


def _refs():
    """[(relpath, lineno, id, code)] —— JS 里所有按 ID 取元素的地方。"""
    out = []
    for path in _js_files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        for i, line in enumerate(io.open(path, encoding="utf-8").read().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            for pat in REF_PATTERNS:
                for m in pat.finditer(line):
                    out.append((rel, i, m.group(1), stripped))
    return out


def _known_ids():
    """index.html + 所有 JS 里被定义过的 ID（含 innerHTML 字符串里拼的）。"""
    known = set()
    for path in [INDEX] + _js_files():
        text = io.open(path, encoding="utf-8").read()
        for pat in DEF_PATTERNS:
            known |= set(pat.findall(text))
    return known


def test_static_resources_exist():
    refs = _refs()
    assert len(refs) > 50, "扫描没抓到多少引用，选择器正则可能失效了"

    known = _known_ids()
    dead = [(rel, i, eid, code) for rel, i, eid, code in refs
            if eid not in known]

    detail = "\n".join(
        "  %s:%d  ID=%s\n      %s" % (rel, i, eid, code)
        for rel, i, eid, code in dead
    )
    assert not dead, (
        "JS 引用了不存在的元素 ID（点到那个分支就会 TypeError）：\n%s" % detail
    )


def test_index_html_has_expected_anchor_ids():
    """index.html 的关键锚点不许被重构删掉。

    这几个 ID 被 JS 反复引用，一旦丢失会让整个面板静默失效，
    比上面的死引用更隐蔽（那个至少会抛错）。
    """
    html = io.open(INDEX, encoding="utf-8").read()
    ids = set(re.findall(r'id\s*=\s*["\']([\w-]+)["\']', html))
    critical = [
        "playlist-preview",     # 歌单预览
        "pl-download-all",      # 歌单全部下载（music.js 死引用的案发现场）
        "panel-settings",       # 设置页
        "settings-save",        # 保存按钮
        "setting-close-to-tray",   # 1.5 关闭到托盘
        "setting-autostart",       # 1.5 开机自启动
    ]
    missing = [i for i in critical if i not in ids]
    assert not missing, "index.html 缺失关键 ID: %s" % missing


def test_no_dangling_id_in_settings_js():
    """1.5 新增的两个开关必须在 HTML 和 JS 两侧都齐全。"""
    html = io.open(INDEX, encoding="utf-8").read()
    js = io.open(os.path.join(STATIC, "js", "settings.js"),
                 encoding="utf-8").read()
    for eid in ("setting-autostart", "setting-close-to-tray"):
        assert 'id="%s"' % eid in html or "id='%s'" % eid in html, \
            "index.html 缺 %s" % eid
        assert eid in js, "settings.js 没操作 %s" % eid
    # 开机启动走独立端点，不塞进「保存」按钮
    assert "/api/settings/autostart" in js
    # 托盘开关走既有 general 段
    assert "close_to_tray" in js
