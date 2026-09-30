# -*- coding: utf-8 -*-
"""L1 静态深挖单测：page_js_urls 纯函数 + probe_static（本地线程 HTTP 服务）。"""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from downloadkit.generic_video import page_js_urls, probe_static

# ---------- page_js_urls（纯函数） ----------


def test_page_js_urls_relative_and_absolute():
    html = (
        '<script src="/js/player.js"></script>'
        "<script src='https://cdn.x.com/lib.js'></script>"
        '<script src="https://cdn.x.com/lib.js"></script>'  # 去重
        "<script>window.inline=1</script>"  # 无 src 跳过
    )
    assert page_js_urls(html, "https://site.com/video/1.html") == [
        "https://site.com/js/player.js",
        "https://cdn.x.com/lib.js",
    ]


def test_page_js_urls_empty():
    assert page_js_urls("", "https://a.com") == []
    assert page_js_urls("<html></html>", "https://a.com") == []


# ---------- probe_static（本地服务） ----------

PAGES = {
    "/l1_inline.html": (
        "text/html",
        '<html><head><title>测试剧 第03集 - 某站</title></head><body>'
        '<script>var conf={url:"https://cdn.x.com/aa0/playlist.m3u8"};</script>'
        "</body></html>",
    ),
    "/l1_via_js.html": (
        "text/html",
        '<html><head><title>JS挖流页</title></head>'
        '<body><script src="/assets/play.js"></script></body></html>',
    ),
    "/assets/play.js": (
        "application/javascript",
        'var video="https://cdn.x.com/bb1/video.mp4?sign=123";',
    ),
    "/no_stream.html": (
        "text/html",
        "<html><head><title>无视频页</title></head><body>纯文本</body></html>",
    ),
    "/third_party.html": (
        "text/html",
        '<html><head><title>只引第三方库</title></head>'
        '<body><script src="https://cdn.jsdelivr.net/npm/jquery@3.6.0/dist/jquery.min.js">'
        "</script></body></html>",
    ),
    "/real.m3u8": ("application/vnd.apple.mpegurl", "#EXTM3U\n#EXT-X-VERSION:3\n"),
}


class _Handler(BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        _Handler.hits.append(self.path)
        ctype, body = PAGES.get(self.path, ("text/html", "<html><title>404</title></html>"))
        data = body.encode("utf-8")
        self.send_response(404 if self.path not in PAGES else 200)
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


def test_probe_inline_stream_and_title():
    """HTML 内联流 → 命中 + title 提取。"""
    r = asyncio.run(probe_static(BASE + "/l1_inline.html", timeout=5))
    assert r["streams"] == ["https://cdn.x.com/aa0/playlist.m3u8"]
    assert r["title"] == "测试剧 第03集 - 某站"


def test_probe_via_js_file():
    """HTML 无流 → 抓页面引用的 JS 再挖。"""
    _Handler.hits.clear()
    r = asyncio.run(probe_static(BASE + "/l1_via_js.html", timeout=5))
    assert r["streams"] == ["https://cdn.x.com/bb1/video.mp4?sign=123"]
    assert r["title"] == "JS挖流页"
    assert "/assets/play.js" in _Handler.hits


def test_probe_no_stream():
    r = asyncio.run(probe_static(BASE + "/no_stream.html", timeout=5))
    assert r["streams"] == []
    assert r["title"] == "无视频页"


def test_probe_third_party_js_not_fetched():
    """第三方库 JS 不抓（省 3s 预算）。"""
    _Handler.hits.clear()
    r = asyncio.run(probe_static(BASE + "/third_party.html", timeout=5))
    assert r["streams"] == []
    assert not any("jsdelivr" in h for h in _Handler.hits)


def test_probe_direct_m3u8_body():
    """URL 返回 #EXTM3U 文本 → URL 本身即流。"""
    r = asyncio.run(probe_static(BASE + "/real.m3u8", timeout=5))
    assert r["streams"] == [BASE + "/real.m3u8"]


def test_probe_connection_refused_no_raise():
    """连接失败不抛异常，返回未命中（探测语义）。"""
    r = asyncio.run(probe_static("http://127.0.0.1:9/x.html", timeout=2))
    assert r == {"streams": [], "title": ""}


def test_probe_invalid_url():
    assert asyncio.run(probe_static("ftp://a.com/x")) == {"streams": [], "title": ""}
