"""P1-6 回归：设置页控件只允许三种模式

2026-09-27 把设置页的控件收成三种形态，并且宽度只留两档（100% / 160px）：

    A 标签在上   .f + .f-label + 控件      （路径、数字）
    B 开关带说明 .f-switch + .f-hint       （复选框）
    C 下拉右对齐 .f-row                   （label 左、select 右）

之前的问题是每处各写各的：并发 100px、日志 140px、历史 120px、重名 160px，
四个开关三套内联样式 —— 视觉上就是「高矮胖瘦各不相同」。

这里锁死两件事：
  1. 新的内联宽度 / 内联开关样式不许再长回来
  2. 三种模式的类必须在 CSS 里真的存在（改名忘改 CSS = 退回裸样式）
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "main.css").read_text(encoding="utf-8")

SETTINGS = HTML.split('id="panel-settings"')[1].split('id="panel-help"')[0]

MODES = ["f-label", "f-row", "f-switch"]


# ---------------- 三模式齐全 ----------------

def test_three_modes_present_with_expected_counts():
    assert len(re.findall(r'class="f-label"', SETTINGS)) >= 9, "标签在上的控件少了"
    assert len(re.findall(r'class="f-row"', SETTINGS)) == 2, "下拉右对齐应为 2 处（重名策略、日志级别）"
    assert len(re.findall(r'class="f-switch"', SETTINGS)) == 3, \
        "开关行应为 3 处（实况照片、开机自启、关闭到托盘；P3-1 后代理换三态 radio）"
    assert len(re.findall(r'class="search-input f-num"', SETTINGS)) == 2, \
        "数字输入应为 2 处（并发、历史）"


def test_modes_defined_in_css():
    for mode in MODES + ["f", "f-num", "f-hint"]:
        assert f".{mode}" in CSS, f"main.css 缺 .{mode} 样式"
    # 宽度档位写死在 CSS 里，别再散落到内联
    assert re.search(r"\.f-num\s*\{[^}]*width:\s*160px", CSS), ".f-num 不是 160px"
    assert re.search(r"\.f-row\s*>\s*select\s*\{[^}]*width:\s*160px", CSS), \
        ".f-row 的下拉不是 160px"


# ---------------- 内联样式不许长回来 ----------------

def test_no_inline_width_left_in_settings():
    """宽度只有 100% 和 160px 两档，都由 CSS 管

    注意用 (?<!-) 排除 min-width / max-width —— 登录状态提示那句
    min-width:160px 是排版约束，不是控件宽度，别误伤。
    """
    for bad in ("width:100px", "width:120px", "width:140px"):
        assert bad not in SETTINGS, f"设置页又出现了内联 {bad}"
    assert not re.search(r"(?<!-)width:160px", SETTINGS), "设置页又出现了内联 width:160px"


def test_no_inline_checkbox_style_left_in_settings():
    """开关的 18px 尺寸统一由 .f-switch 管，不再内联"""
    assert "width:18px;height:18px" not in SETTINGS, "设置页还有内联开关样式"


def test_no_inline_block_label_style_left():
    """标签样式（display:block + 13px + 次要色）统一走 .f-label"""
    assert "margin-bottom:4px;font-size:13px;color:var(--text-secondary)" not in HTML, \
        "还有内联 label 样式"


# ---------------- 结构 ----------------

def test_f_row_is_label_left_control_right():
    """下拉模式必须靠 space-between 把 select 顶到右边"""
    css_block = re.search(r"\.f-row\s*\{([^}]*)\}", CSS)
    assert css_block, "main.css 缺 .f-row"
    assert "justify-content: space-between" in css_block.group(1)


def test_switch_rows_are_labelled():
    """开关行的 label 必须 for 到控件（点文字也能切，也方便读屏）"""
    rows = re.findall(r'<div class="f-switch">(.*?)</div>', SETTINGS, re.S)
    # P3-1 后代理区的「启用代理」开关换成三态 radio，不再是 f-switch 行
    assert len(rows) == 3
    for row in rows:
        m = re.search(r'<label for="([^"]+)"', row)
        assert row, "开关行是空的"
        assert m, f"开关行缺 for：{row[:80]}"
        assert f'id="{m.group(1)}"' in row, f"label for 指向的控件不在同一行：{m.group(1)}"


def test_controls_still_have_their_ids():
    """改样式不能动 id —— settings.js 全靠 id 读写"""
    for _id in ("setting-rename-strategy", "setting-max-concurrent", "setting-log-level",
                "setting-history-max-records", "setting-motion-photo-default",
                "setting-proxy-mode-off", "setting-proxy-mode-system",
                "setting-proxy-mode-manual", "proxy-test-btn",
                "setting-autostart", "setting-close-to-tray",
                "setting-download-dir", "setting-download-dir-music"):
        assert f'id="{_id}"' in SETTINGS, f"#{_id} 不见了"
