"""P3-3 音乐页 / 资源页下载按钮状态统一

改之前是三套行为：

  1. 音乐页图标按钮：dl-spin / dl-ok / dl-fail 持久保留，title 是它
     唯一的状态词 —— 但「下载中」时 title 还停在上一次的值上。
  2. 资源页主按钮：完成/失败 2 秒后抹回「下载」，「下过了」的反馈
     转眼就没了，用户还得自己去下载目录确认。
  3. 资源页内联按钮：压根没有状态 —— downloadResource 内部硬取
     #resource-download-btn，状态跑到主按钮上；批量列表视图里主按钮
     不在 DOM，btn.disabled 直接 null 崩。

统一后的约定（本文件钉住的就是这些约定）：

  - 每个按钮自己管自己的状态（内联按钮把 this 传进去）
  - 三态文案两页一致：下载中… / 已下载 / 下载失败
  - 完成与失败态都留在按钮上，不自动抹回 idle
  - null 防护：找不到落点按钮时静默返回，不崩
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"

RES = (STATIC / "js" / "resource.js").read_text(encoding="utf-8")
MUSIC = (STATIC / "js" / "music.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


# ---------------- 资源页：状态落点 ----------------

def test_download_resource_takes_btn_param():
    """btn 是参数不是硬取主按钮 —— 状态要落在被点的那个按钮上"""
    m = re.search(r"function downloadResource\(([^)]*)\)", RES)
    assert m, "找不到 downloadResource"
    params = [p.strip() for p in m.group(1).split(",")]
    assert params == ["url", "platform", "btn"], f"签名应为 (url, platform, btn)，实际 {params}"


def test_download_resource_defaults_and_null_guard():
    """不传 btn 落首个预览区的下载按钮（单资源详情的原路径）；落点不存在时静默返回"""
    body = RES.split("function downloadResource")[1].split("function pollResourceDownload")[0]
    assert re.search(r"btn\s*=\s*btn\s*\|\|\s*document\.querySelector\('\.preview-download-btn'\)", body), \
        "没保留主按钮默认落点（双 Tab 后按钮 class 化，不再用 id 查询）"
    assert re.search(r"if\s*\(!btn\)\s*return", body), \
        "缺 null 防护：批量列表里主按钮不在 DOM 会直接崩"


def test_inline_buttons_pass_themselves():
    """内联列表按钮点击时把自己传进去"""
    assert "downloadResource(this.dataset.url, this.dataset.platform, this)" in RES, \
        "内联按钮没把 this 传给 downloadResource，状态又会跑到主按钮上"


# ---------------- 资源页：状态持久 ----------------

def test_no_two_second_revert():
    """完成/失败后不再 2 秒抹回「下载」——反馈不能转眼就消失"""
    # 恢复 idle 的写法是 btn.innerHTML = iconHtml + '下载';（分号定界，
    # 不会误伤 '下载中…' 这种前缀）
    assert "iconHtml + '下载';" not in RES, \
        "还有 2 秒抹回 idle 的代码，完成态留不住"


def test_resource_state_words_match_music():
    """两页三态文案一致：下载中… / 已下载 / 下载失败"""
    assert "iconHtml + '下载中…'" in RES, "资源页缺「下载中…」态"
    assert "iconHtml + '已下载'" in RES, "资源页缺「已下载」完成态"
    assert "iconHtml + '下载失败'" in RES, "资源页缺「下载失败」态"
    # 音乐页图标按钮没有可见文案，状态词走 title
    assert "title = '已下载'" in MUSIC, "音乐页缺「已下载」"
    assert "title = '下载失败'" in MUSIC, "音乐页缺「下载失败」"


def test_resource_terminal_states_enable_button():
    """完成/失败后按钮恢复可点（对齐音乐页 disabled=false，可再下一次）"""
    done_block = RES.split("info.status === 'done'")[1].split("} else if")[0]
    assert "btn.disabled = false" in done_block, "完成态按钮没解锁"
    fail_block = RES.split("info.status === 'failed'")[1].split("} else {")[0]
    assert "btn.disabled = false" in fail_block, "失败态按钮没解锁，没法点重试"


# ---------------- 音乐页：下载中的状态词 ----------------

def test_music_downloading_title():
    """图标按钮下载中时 title 必须同步，否则它停在上一次的状态词上"""
    handle = MUSIC.split("function handleDownload")[1].split("function pollDownload")[0]
    assert "btn.title = '下载中'" in handle, "点击发起下载时没设「下载中」"
    update = MUSIC.split("function updateDlBtn")[1].split("function hideBulkBar")[0]
    assert "btn.title = '下载中'" in update, "轮询回 downloading 时没维护「下载中」"


def test_inline_button_template_exists():
    """内联按钮是 resource.js 拼出来的字符串，确保类名没改走"""
    assert "inline-dl-btn" in RES, "resource.js 里没有内联下载按钮的模板"
