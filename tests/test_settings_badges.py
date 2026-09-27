"""P1-4 回归：设置页备注治理

2026-09-27 两件事：

  1. **徽标统一** —— 原来 8 处「立即生效 / 需重启 / 下次启动生效」全是
     各写各的内联 style（字号、颜色、margin 都不一致），收成一种
     `.eff` 药丸样式 + 三个语义修饰类。
  2. **长文迁出** —— Cookie 那张 20 行的说明卡、扫码登录的说明卡整体搬进
     解答页，设置页只留一句话 + `data-help` 内链。

这里要防的是两件事回潮：有人再往设置页塞内联徽标，或者把长文复制回来
（重复内容日后必然改漏一边，解答页刚建好就会跟设置页打架）。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"

HTML = (STATIC / "index.html").read_text(encoding="utf-8")

SETTINGS = HTML.split('id="panel-settings"')[1].split('id="panel-help"')[0]
HELP = HTML.split('id="panel-help"')[1].split("<!-- Toast容器 -->")[0]

BADGE_KINDS = {"eff-live", "eff-restart", "eff-next"}


# ---------------- 徽标 ----------------

def test_badges_all_use_one_class():
    """设置页的生效提示必须全是 .eff，且只有三种语义"""
    badges = re.findall(r'<span class="(eff[^"]*)">([^<]+)</span>', SETTINGS)
    assert badges, "设置页一个徽标都没有？那说明被误删了"

    for cls, text in badges:
        kinds = set(cls.split()) - {"eff"}
        assert kinds <= BADGE_KINDS, f"徽标 {text} 用了未定义的修饰类 {cls}"

    texts = {t for _, t in badges}
    assert texts <= {"立即生效", "需重启", "下次启动生效"}, f"出现新徽标文案：{texts}"

    # 三种都要在场（少一种说明有人删掉了对应提示）
    present = {t for _, t in badges}
    assert present == {"立即生效", "需重启", "下次启动生效"}, present


def test_no_inline_badge_style_left():
    """旧的内联徽标样式一个都不能留（字号 11px + margin-left 8px 是它的指纹）"""
    assert 'font-size:11px;color:var(--success);margin-left:8px' not in HTML, \
        "还有内联的「立即生效」徽标"
    assert 'font-size:11px;color:var(--warning);margin-left:8px' not in HTML, \
        "还有内联的「需重启」徽标"
    assert 'color:var(--warning)">下次启动生效</span>' not in HTML, \
        "还有内联的「下次启动生效」徽标"


def test_badge_css_exists():
    """样式类得真的在 CSS 里，否则徽标退化成裸文本"""
    css = (STATIC / "css" / "main.css").read_text(encoding="utf-8")
    assert ".eff {" in css, "main.css 缺 .eff"
    for kind in BADGE_KINDS:
        assert f".{kind}" in css, f"main.css 缺 .{kind}"


# ---------------- 长文迁出 ----------------

def test_long_cookie_card_moved_out_of_settings():
    """Cookie 长卡的指纹不能出现在设置页（它们应该只在解答页）"""
    for marker in ("# Netscape HTTP Cookie File", "任选一种",
                   "Application</b> → <b>Cookies"):
        assert marker not in SETTINGS, f"设置页还留着长文片段：{marker}"
        assert marker in HELP, f"解答页丢了这段：{marker}"


def test_login_card_moved_out_of_settings():
    """扫码登录的长说明同样只在解答页

    注意设置页现在留的是一句话短说明（可以含「登录一次长期有效」这类短句），
    所以断言的必须是长卡独有的片段，不能拿短句当指纹。
    """
    for marker in ("扫码即可", "功能需要登录抖音"):
        assert marker not in SETTINGS, f"设置页还留着扫码登录长说明：{marker}"
        assert marker in HELP, f"解答页丢了扫码登录说明：{marker}"


def test_every_help_link_points_to_existing_anchor():
    """设置页每个 data-help 内链，解答页里都得有对应锚点（点了不能没反应）"""
    links = re.findall(r'class="help-link"\s+data-help="([^"]+)"', SETTINGS)
    assert len(links) >= 2, f"设置页应至少有 2 个解答内链，实际 {links}"

    anchors = set(re.findall(r'<section class="help-block" id="([^"]+)"', HELP))
    for target in links:
        assert target in anchors, f"内链指向的 #{target} 在解答页不存在"


def test_help_js_binds_data_help():
    """内链的点击是 help.js 绑的，别在重构时被漏掉"""
    help_js = (STATIC / "js" / "help.js").read_text(encoding="utf-8")
    assert "[data-help]" in help_js, "help.js 没绑 [data-help]"
    assert "openHelp(el.dataset.help" in help_js, "help.js 没把锚点透传"
    css = (STATIC / "css" / "main.css").read_text(encoding="utf-8")
    assert ".help-link" in css, "main.css 缺 .help-link 样式"
