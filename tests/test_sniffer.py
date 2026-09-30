# -*- coding: utf-8 -*-
"""downloadkit.sniffer 纯函数单测：提流 / 去重 / 主子区分 / 播放器地址三级来源。"""
from downloadkit.sniffer import (
    dedupe_streams,
    extract_stream_urls,
    find_player_url,
    prefer_main_streams,
)

# ---------- 提流 ----------

def test_extract_basic_m3u8_mp4():
    text = 'var a = "https://cdn.x.com/aa0c0684/playlist.m3u8"; fetch("https://b.com/v/1.mp4?sign=abc#t")'
    urls = extract_stream_urls(text)
    assert urls == [
        "https://cdn.x.com/aa0c0684/playlist.m3u8",
        "https://b.com/v/1.mp4?sign=abc#t",
    ]


def test_extract_excludes_ads_and_preview():
    text = """
    https://cdn.x.com/playlist.m3u8
    https://cdn.x.com/trailer.m3u8
    https://cdn.x.com/preview.mp4
    https://cdn.x.com/ads/play.m3u8
    https://cdn.x.com/vod_ad/x.m3u8
    https://cdn.x.com/advert/1.mp4
    https://cdn.plyr.io/static/blank.mp4
    """
    urls = extract_stream_urls(text)
    assert urls == ["https://cdn.x.com/playlist.m3u8"]


def test_extract_blank_filter_word_boundary():
    """blank 占位流排除，但 blankless 之类子串不误伤。"""
    text = "https://a.com/static/blank.mp4 https://b.com/blankless_video.mp4"
    assert extract_stream_urls(text) == ["https://b.com/blankless_video.mp4"]


def test_extract_dedupes_and_rstrips():
    text = '("https://a.com/x.m3u8", "https://a.com/x.m3u8"); <url>https://b.com/y.m3u8,</url>'
    urls = extract_stream_urls(text)
    assert urls == ["https://a.com/x.m3u8", "https://b.com/y.m3u8"]


def test_extract_empty():
    assert extract_stream_urls("") == []
    assert extract_stream_urls(None) == []


# ---------- 去重（归一化签名参数） ----------

def test_dedupe_same_host_path_different_query():
    urls = [
        "https://cdn.x.com/v/playlist.m3u8?expires=1&sign=aaa",
        "https://cdn.x.com/v/playlist.m3u8?expires=2&sign=bbb",
        "https://cdn.x.com/v/other.m3u8",
    ]
    out = dedupe_streams(urls)
    assert out == [
        "https://cdn.x.com/v/playlist.m3u8?expires=1&sign=aaa",
        "https://cdn.x.com/v/other.m3u8",
    ]


# ---------- 主/子播放列表 ----------

def test_prefer_main_over_sub():
    urls = [
        "https://cdn.x.com/aa/640x360/video.m3u8",
        "https://cdn.x.com/aa/playlist.m3u8",
        "https://cdn.x.com/aa/1280x720/video.m3u8",
    ]
    assert prefer_main_streams(urls) == ["https://cdn.x.com/aa/playlist.m3u8"]


def test_prefer_sub_when_only_sub():
    urls = ["https://cdn.x.com/aa/640x360/video.m3u8"]
    assert prefer_main_streams(urls) == urls


def test_prefer_keeps_mp4_and_plain():
    urls = [
        "https://cdn.x.com/640x360/video.m3u8",
        "https://cdn.x.com/movie.mp4",
        "https://cdn.x.com/live.m3u8",
    ]
    out = prefer_main_streams(urls)
    assert "https://cdn.x.com/movie.mp4" in out
    assert "https://cdn.x.com/live.m3u8" in out
    assert "https://cdn.x.com/640x360/video.m3u8" not in out


def test_prefer_empty():
    assert prefer_main_streams([]) == []


# ---------- 播放器地址三级来源 ----------

def test_player_from_xhr_body_first():
    """a. XHR 响应体优先（样本2 content_pframe_url）"""
    bodies = [
        '{"code":0,"data":{"url":"https://pframe.xgcartoon.com/pframe/player.htm?vid=abc"}}',
    ]
    dom = ["https://other.com/embed.html"]
    assert find_player_url(bodies, dom).startswith("https://pframe.xgcartoon.com/pframe/player.htm")


def test_player_from_dom_iframe_when_no_body():
    """b. 无 XHR 命中 → DOM iframe src（过滤 data:，播放器特征优先）"""
    dom = ["data:text/html,xxx", "https://cdn.com/ads/frame.html",
           "https://pframe.site.com/pframe/player.htm?vid=1"]
    assert "pframe.site.com" in find_player_url([], dom)


def test_player_dom_first_http_when_no_hint():
    dom = ["https://plain.com/frame1.html"]
    assert find_player_url([], dom) == "https://plain.com/frame1.html"


def test_player_from_page_html_last():
    """c. 兜底：页面 HTML 里的 player 链接"""
    html = '<script>var p="https://static.x.com/player/embed.htm?vid=9";</script>'
    assert find_player_url([], [], html) == "https://static.x.com/player/embed.htm?vid=9"


def test_player_not_found():
    assert find_player_url([], [], "<html>no player</html>") == ""
    assert find_player_url([], [], "") == ""
