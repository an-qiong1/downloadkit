"""P1-5 回归：解答页（panel-help）的结构、进出与内容

2026-09-27 新增的解答页有两个容易被改坏的地方：

  1. **进出链路** —— 它不占侧边栏导航，靠设置页的内链进入、靠
     window.__switchTab 返回。app.js 是 IIFE，switchTab 不透出去，
     解答页就成了单程票：进得来、回不去。
  2. **目录锚点** —— 滚动容器是 .content（overflow:auto），不是 .main。
     早先用 behavior:'smooth' 在这套环境里动画不跑，点目录看着像没反应。

另外把页面内容（FAQ 条数、报错表行数）也钉住，免得日后清理时把
整个解答页掏空 —— 这页是设置页长文唯一的去处。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
HELP = (STATIC / "js" / "help.js").read_text(encoding="utf-8")
APP = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
UTILS = (STATIC / "js" / "utils.js").read_text(encoding="utf-8")

# panel-help 从属于 content，切片取它自己的原文
HELP_HTML = HTML.split('id="panel-help"')[1].split("<!-- Toast容器 -->")[0] \
    if "id=\"panel-help\"" in HTML else ""


# ---------------- 结构 ----------------

def test_panel_exists_but_stays_out_of_sidebar():
    """解答页存在，但不占侧边栏那一栏（这是当初的明确取舍）"""
    assert 'id="panel-help"' in HTML, "缺 panel-help"
    assert 'data-tab="help"' not in HTML, "解答页不该出现在侧边栏导航里"
    assert "'help': '解答'" in UTILS, "tabTitles 缺 help，页头会显示原始 tab 名"


def test_help_has_six_blocks_matching_toc():
    """目录 6 项 ↔ 6 个内容块，一一对应（少一个就是点目录没反应）"""
    blocks = re.findall(r'<section class="help-block" id="([^"]+)"', HELP_HTML)
    anchors = re.findall(r'class="help-toc-link" data-anchor="([^"]+)"', HELP_HTML)
    assert len(blocks) == 6, f"内容块应有 6 个，实际 {blocks}"
    assert anchors == blocks, f"目录与内容块对不上：目录 {anchors} vs 块 {blocks}"


def test_entry_button_lives_in_about_group():
    """入口在设置页「关于」组里，且 help.js 绑到了它"""
    settings_html = HTML.split('id="panel-settings"')[1].split('id="panel-help"')[0]
    assert 'id="open-help"' in settings_html, "关于组缺解答入口"
    assert "getElementById('open-help')" in HELP or "$('#open-help')" in HELP
    assert 'id="help-back"' in HTML, "解答页缺返回按钮"
    assert "closeHelp" in HELP


# ---------------- 进出链路 ----------------

def test_app_exposes_switch_tab_and_close_sidebar():
    """app.js 必须把内部函数透出去，否则解答页回不去、侧边栏收不起来"""
    assert "window.__switchTab = switchTab" in APP, "app.js 没暴露 __switchTab"
    assert "window.__closeSidebar = closeSidebar" in APP, "app.js 没暴露 __closeSidebar"
    assert "window.__switchTab" in HELP, "help.js 没用 __switchTab 返回"
    assert "window.__closeSidebar" in HELP, "help.js 没用 __closeSidebar 收侧边栏"


def test_return_goes_to_origin_tab_not_always_settings():
    """返回要回「进来时的那个页面」，而不是写死设置页"""
    # 记录来源：只在 activeTab !== 'help' 时覆盖
    assert "state.activeTab !== 'help'" in HELP
    assert "backTab = state.activeTab" in HELP
    # 返回时避开自己
    assert "backTab !== 'help'" in HELP


def test_anchor_uses_instant_scroll_and_correct_container():
    """锚点必须瞬时滚（smooth 在这环境不跑），且滚 .content 不是 .main"""
    assert "behavior: 'auto'" in HELP, "锚点不能用 smooth：动画不跑等于没反应"
    assert "behavior: 'smooth'" not in HELP
    assert "querySelector('.content')" in HELP, "滚动容器找错了：.main 是 overflow:hidden"
    assert "querySelector('.main')" not in HELP


def test_data_help_entries_bound():
    """设置页里所有 data-help 入口（P1-4 迁长文时会大量出现）都绑上"""
    assert "('[data-help]')" in HELP or '"[data-help]"' in HELP
    assert "openHelp(el.dataset.help" in HELP, "没把锚点透给 openHelp"


# ---------------- 内容不能被掏空 ----------------

def test_content_is_not_empty():
    """FAQ 与报错表是这页的主体，别在清理时被删光"""
    faq = re.search(r'<dl class="help-faq">(.*?)</dl>', HELP_HTML, re.S)
    assert faq, "缺 FAQ"
    assert len(re.findall(r"<dt>", faq.group(1))) >= 6, "FAQ 少于 6 条"

    table = re.search(r'<table class="help-table">(.*?)</table>', HELP_HTML, re.S)
    assert table, "缺报错对照表"
    rows = re.findall(r"<tr>\s*<td>", table.group(1))
    assert len(rows) >= 5, f"报错对照表少于 5 行，实际 {len(rows)}"


def test_help_js_ids_exist():
    """help.js 里 $() 引用的元素必须在 HTML 里（防止改名漏同步）"""
    ids = set(re.findall(r'\bid="([^"]+)"', HTML))
    for ref in re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", HELP):
        assert ref in ids, f"help.js 引用了不存在的 #{ref}"
    for ref in re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", HELP):
        assert ref in ids, f"help.js 引用了不存在的 #{ref}"
