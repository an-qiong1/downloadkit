# -*- coding: utf-8 -*-
"""选集展开单测：模板化纯函数 + 样本1/样本2 仿造页聚类 + 本地 L1 集成。"""
import asyncio
import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from downloadkit.episodes import (
    expand_episodes, extract_from_html, label_and_order, template_path,
)

# ---------- 模板化 ----------


def test_template_path_samples():
    # 样本1：base64 段（含扩展名）
    assert template_path("/v_play/bXZfMTEwMzAtbm1fMTk1.html") == "/v_play/{b64}.html"
    # 纯数字段
    assert template_path("/movie/11030.html") == "/movie/{id}.html"
    # 纯字母 slug 不模板化（防误聚）
    assert template_path("/detail/shixiongashixiong-jinlei") == \
        "/detail/shixiongashixiong-jinlei"
    # 样本2 播放页最后一段（10 位字母数字混合）
    assert template_path("/video/slug/udWdMztqNU.html") == "/video/slug/{b64}.html"
    # 静态资源路径原样
    assert template_path("/assets/play.js") == "/assets/play.js"
    assert template_path("/user/page_direct") == "/user/page_direct"
    # 短段内嵌数字 → 数字段抽为 {id}（§4.6.2「path 中含数字段→{id}」）
    assert template_path("/watch/ep1.html") == "/watch/ep{id}.html"
    assert template_path("/show-1234.html") == "/show-{id}.html"


def test_label_and_order():
    assert label_and_order("第01集 1") == ("第1集", 1)
    assert label_and_order("第 195 集") == ("第195集", 195)
    assert label_and_order("12") == ("第12集", 12)
    label, order = label_and_order("虚天战纪-A-上")
    assert order == -1 and label == "虚天战纪-A-上"
    assert label_and_order("第5话") == ("第5集", 5)


# ---------- 样本1 仿造：/v_play/{b64}.html 195 条 + 特殊集 ----------


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode().rstrip("=")


def _sample1_html() -> str:
    links = []
    for n in range(1, 196):
        links.append(f'<a href="/v_play/{_b64(f"mv_11030-nm_{n}")}.html">{n}</a>')
    # 特殊集（非数字文本，混在数字序列中 → DOM 序垫底）
    links.append(f'<a href="/v_play/{_b64("mv_11030-nm_x1")}.html">虚天战纪-A-上</a>')
    links.append(f'<a href="/v_play/{_b64("mv_11030-nm_x2")}.html">虚天战纪-A-下</a>')
    nav = '<a href="/movie/11030.html">详情</a><a href="/movie/11031.html">推荐</a>'
    return f"<html><body><div class='paly_list_btn'>{''.join(links)}</div>{nav}</body></html>"


def test_extract_sample1():
    r = extract_from_html(_sample1_html(), "https://www.cz4k.com/v_play/bXZfMTEwMzAtbm1fMTk1.html")
    assert r["count"] == 197
    g = r["groups"][0]
    assert g["template"] == "/v_play/{b64}.html"
    items = g["items"]
    # 数字集升序 1..195，特殊集按 DOM 序垫底
    assert items[0]["label"] == "第1集"
    assert items[194]["label"] == "第195集"
    assert items[195]["label"] == "虚天战纪-A-上"
    assert items[196]["label"] == "虚天战纪-A-下"
    # 详情页/推荐链接（2 条 < MIN_GROUP）不入组
    assert all(g2["template"] != "/movie/{id}.html" for g2 in r["groups"])


# ---------- 样本2 仿造：page_direct query + a 内 span ----------


def _sample2_html() -> str:
    links = []
    for n in range(1, 162):
        cid = _b64(f"ch{n}")[:10]
        links.append(
            f'<div class="col-12"><a href="/user/page_direct?'
            f'cartoon_id=shixiongashixiong-jinlei&chapter_id={cid}" '
            f'class="goto-chapter chapter-box">'
            f'<span class="title">第{n:02d}集</span>'
            f'<span class="sequence">{n}</span></a></div>'
        )
    return "<html><body>" + "".join(links) + "</body></html>"


def test_extract_sample2():
    r = extract_from_html(
        _sample2_html(),
        "https://www.cnxgct.com/video/shixiongashixiong-jinlei/udWdMztqNU.html",
    )
    assert r["count"] == 161
    g = r["groups"][0]
    assert "page_direct" in g["template"]
    items = g["items"]
    assert items[0]["label"] == "第1集" and items[0]["url"].startswith("http")
    assert items[0]["url"].endswith("chapter_id=" + _b64("ch1")[:10])
    assert items[160]["label"] == "第161集"


def test_sample2_outlier_cartoon_id_filtered():
    """混入其他剧的 page_direct 链接（占比 <10%）应被准常量过滤剔除。"""
    html = _sample2_html()
    html = html.replace(
        "</body>",
        '<a href="/user/page_direct?cartoon_id=other-show&chapter_id=zzz1">第1集</a>'
        "</body>",
    )
    r = extract_from_html(html, "https://www.cnxgct.com/video/x/y.html")
    urls = [i["url"] for i in r["groups"][0]["items"]]
    assert r["count"] == 161
    assert not any("other-show" in u for u in urls)


def test_detail_page_play_entry_repairs_ep1():
    """详情页结构：第1集做成「播放」入口（chapter_id 独立），数字集从第2集起
    → 入口词补为第1集，排序后首项=第1集、末项=第161集（xgcartoon 实测形态）。"""
    links = ['<a href="/user/page_direct?cartoon_id=shixiongashixiong-jinlei'
             '&chapter_id=ENTRY00001"><span>播放</span></a>']
    for n in range(2, 162):
        links.append(
            f'<a href="/user/page_direct?cartoon_id=shixiongashixiong-jinlei'
            f'&chapter_id=CH{n:04d}x"><span class="title">第{n:02d}集</span></a>'
        )
    html = "<html><body>" + "".join(links) + "</body></html>"
    r = extract_from_html(html, "https://www.xgcartoon.com/detail/x")
    assert r["count"] == 161
    items = r["groups"][0]["items"]
    assert items[0]["label"] == "第1集"
    assert items[1]["label"] == "第2集"
    assert items[-1]["label"] == "第161集"
    assert "ENTRY00001" in items[0]["url"]


def test_nontext_member_inserted_by_dom_not_appended():
    """无数字成员按 DOM 序插入数字序列（特殊集在中间 → 留在中间，不垫底）。"""
    parts = []
    for n in (1, 2):
        parts.append(f'<a href="/v/{n}.html">第{n}集</a>')
    parts.append('<a href="/v/9001.html">虚天战纪-A-上</a>')
    for n in (3, 4):
        parts.append(f'<a href="/v/{n}.html">第{n}集</a>')
    r = extract_from_html("".join(parts), "https://a.com/p")
    labels = [i["label"] for i in r["groups"][0]["items"]]
    assert labels == ["第1集", "第2集", "虚天战纪-A-上", "第3集", "第4集"]


# ---------- 基础规则 ----------


def test_min_group_filter():
    html = '<a href="/play/1.html">1</a><a href="/play/2.html">2</a>'
    assert extract_from_html(html, "https://a.com/x") == {"count": 0, "groups": []}


def test_dedupe_relative_and_non_http():
    html = (
        '<a href="/ep/1.html">第1集</a>'
        '<a href="/ep/1.html">第1集</a>'          # 重复 → 去重
        '<a href="/ep/2.html">第2集</a>'
        '<a href="/ep/3.html">第3集</a>'
        '<a href="mailto:x@y.com">mail</a>'
        '<a href="javascript:void(0)">js</a>'
        '<a href="#top">top</a>'
    )
    r = extract_from_html(html, "https://a.com/detail/1")
    assert r["count"] == 3
    assert all(i["url"].startswith("https://a.com/ep/") for i in r["groups"][0]["items"])


def test_numeric_sort_not_lexicographic():
    html = "".join(f'<a href="/v/{n}.html">第{n}集</a>' for n in [10, 2, 1, 100])
    r = extract_from_html(html, "https://a.com/p")
    labels = [i["label"] for i in r["groups"][0]["items"]]
    assert labels == ["第1集", "第2集", "第10集", "第100集"]


def test_second_group_ordering():
    """多组时按成员数降序返回。"""
    html = "".join(f'<a href="/a/{n}.html">第{n}集</a>' for n in range(1, 6))
    html += "".join(f'<a href="/b/{n}.html">x{n}</a>' for n in range(1, 4))
    r = extract_from_html(html, "https://a.com/p")
    assert [g["count"] for g in r["groups"]] == [5, 3]


# ---------- 本地 L1 集成（关掉 yt-dlp 与浏览器） ----------

PAGES = {
    "/play.html": (
        "text/html",
        "<html><head><title>测试剧第01集在线播放</title></head><body>"
        + "".join(f'<a href="/watch/ep{n}.html">第{n}集</a>' for n in range(1, 11))
        + "</body></html>",
    ),
    "/plain.html": ("text/html", "<html><title>无选集</title><body>hi</body></html>"),
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        ctype, body = PAGES.get(self.path, ("text/html", "<html><title>404</title></html>"))
        data = body.encode("utf-8")
        self.send_response(200 if self.path in PAGES else 404)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静音
        pass


def _serve() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


SRV, BASE = _serve()


def test_expand_static_l1():
    r = asyncio.run(expand_episodes(
        BASE + "/play.html", try_ytdlp=False, use_browser=False))
    assert r["method"] == "static"
    assert r["count"] == 10
    assert r["title"] == "测试剧第01集在线播放"
    assert r["error"] == ""


def test_expand_no_episodes_fallback():
    """路3：回退单集 + error 提示。"""
    r = asyncio.run(expand_episodes(
        BASE + "/plain.html", try_ytdlp=False, use_browser=False))
    assert r["method"] == "none"
    assert r["count"] == 0
    assert "未识别到选集" in r["error"]


def test_expand_invalid_url():
    r = asyncio.run(expand_episodes(
        "ftp://a.com/x", try_ytdlp=False, use_browser=False))
    assert r["method"] == "none" and r["count"] == 0
