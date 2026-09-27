"""P1-2 回归：设置页 5 组卡片的结构与归属

2026-09-27 把设置页从一条流水账重排成 5 组卡片：
    下载 / 应用 / 网络 / 启动与后台 / 关于

这类「把大段 HTML 拆开重组」的改动，最容易出的事故是：

  1. 块复制粘贴重复 —— 同一个 input 出现两次，id 撞车，浏览器按第一个算，
     表面上看不出来，保存时却可能读到旧的那个
  2. 块搬丢了 / 少包一层 div —— 设置页直接白屏或后半截控件全没反应
  3. 控件放错组 —— 「历史记录条数」跑到「下载」组里，用户找不着

所以这里断言：组顺序、控件归属、id 全局唯一、整份 HTML 标签配平。
另外把版本号和 pyproject.toml 钉死，免得发版忘了同步关于页。
"""

import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"

HTML = (STATIC / "index.html").read_text(encoding="utf-8")

GROUPS = ["下载", "应用", "网络", "启动与后台", "关于"]


# ---------------- 组结构 ----------------

def _group_blocks() -> list:
    """按出现顺序取出每个 setting-group 的 <section>…</section> 原文"""
    blocks, pos = [], 0
    while True:
        i = HTML.find('<section class="setting-group">', pos)
        if i < 0:
            break
        j = HTML.index("</section>", i)
        blocks.append(HTML[i:j])
        pos = j
    return blocks


def test_five_groups_in_order():
    blocks = _group_blocks()
    titles = []
    for b in blocks:
        m = re.search(r'setting-group-title"><i[^>]*></i>([^<]+)</h4>', b)
        assert m, "有组卡片缺 setting-group-title"
        titles.append(m.group(1).strip())
    assert titles == GROUPS, f"组顺序/数量不对：{titles}"


def test_controls_sit_in_the_right_group():
    """控件归属：搬块时最容易把某个控件落在错的组里"""
    blocks = _group_blocks()
    by_title = {}
    for b in blocks:
        m = re.search(r'setting-group-title"><i[^>]*></i>([^<]+)</h4>', b)
        by_title[m.group(1).strip()] = b

    expect = {
        "下载": ["setting-download-dir", "setting-rename-strategy", "setting-motion-photo-default"],
        "应用": ["setting-max-concurrent", "setting-log-level", "setting-history-max-records"],
        "网络": ["setting-proxy-enabled", "setting-cookie-douyin", "setting-cookie-bilibili",
                 "dy-login-btn"],
        "启动与后台": ["setting-autostart", "setting-close-to-tray"],
        "关于": ["setting-version"],
    }
    for title, ids in expect.items():
        body = by_title[title]
        for _id in ids:
            assert f'id="{_id}"' in body, f"#{_id} 不在「{title}」组里"

    # 反向：组里不该出现别的组的控件
    assert "setting-history-max-records" not in by_title["下载"]
    assert "setting-proxy-enabled" not in by_title["应用"]


def test_network_group_has_subtitles():
    """网络组一张卡塞了三件事，靠子标题区分；另两组不需要"""
    net = [b for b in _group_blocks() if "网络" in b][0]
    subs = re.findall(r'class="setting-subtitle">([^<]+)<', net)
    assert len(subs) == 3, f"网络组应有 3 个子标题，实际 {subs}"
    assert any("代理" in s for s in subs)
    assert any("扫码" in s for s in subs)
    assert any("Cookie" in s for s in subs)

    for b in _group_blocks():
        if "网络" in b:
            continue
        assert 'class="setting-subtitle"' not in b, "单事件组不该再塞子标题"


def test_old_h4_section_headers_gone():
    """组内旧的 border-top 小标题应该一个不剩（组卡片 title 接管了）"""
    body = HTML.split('id="panel-settings"')[1].split("<!-- 收藏歌单面板 -->")[0]
    assert 'font-weight:500;font-size:14px' not in body, "设置页还有旧小标题没清干净"


# ---------------- 唯一性与配平 ----------------

def test_all_ids_unique():
    """重组块最怕复制粘贴重复，id 撞车浏览器只认第一个"""
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    dup = {i for i in ids if ids.count(i) > 1}
    assert not dup, f"重复 id：{sorted(dup)}"


class _Balance(HTMLParser):
    VOID = {"br", "img", "input", "meta", "link", "hr", "source", "area",
            "base", "col", "embed", "param", "track", "wbr", "!doctype"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errs = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack:
            self.errs.append(f"多余 </{tag}> 行 {self.getpos()[0]}")
            return
        open_tag, line = self.stack.pop()
        if open_tag != tag:
            self.errs.append(
                f"行 {self.getpos()[0]} </{tag}> 撞上行 {line} 的 <{open_tag}>"
            )


def test_whole_document_tags_balanced():
    """整份 HTML 必须严格配平

    历史包袱：这份文件长期少一个 `.content` 的 </div>，靠浏览器容错兜着，
    重组设置面板时才被 HTMLParser 露出来 —— 现在补上了，锁死别再丢。
    """
    p = _Balance()
    p.feed(HTML)
    assert not p.errs, "标签不配平：" + "; ".join(p.errs)
    assert not [t for t, _ in p.stack if t != "html"], f"有标签没闭合：{p.stack}"


# ---------------- 版本号 ----------------

def test_about_version_matches_pyproject():
    """关于页写死的版本号必须和 pyproject.toml 一致"""
    m = re.search(r'id="setting-version"[^>]*>([^<]+)<', HTML)
    assert m, "关于组缺 version 元素"
    shown = m.group(1).strip().lstrip("v")

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    real = data["project"]["version"]
    assert shown == real, f"关于页显示 v{shown}，pyproject 是 {real}"
