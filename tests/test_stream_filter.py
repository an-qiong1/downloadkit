# -*- coding: utf-8 -*-
"""P5 选流去重单测（计划书 §4.3 / §5.1 stream_filter.py）。

覆盖：干扰流排除 / 归一化 stream_key / 跨签名去重保首见 / 主子列表区分。
"""
from downloadkit.stream_filter import (
    dedupe_streams,
    extract_stream_urls,
    prefer_main_streams,
    stream_key,
)


class TestStreamKey:
    def test_signature_query_ignored(self):
        """同 host+path、不同 expires/sign/ts → 同 key（§4.3 去重行）。"""
        a = stream_key("https://cdn.x.com/hls/v/index.m3u8?expires=1&sign=aa")
        b = stream_key("https://cdn.x.com/hls/v/index.m3u8?expires=99&sign=bb&ts=5")
        assert a == b == "https://cdn.x.com/hls/v/index.m3u8"

    def test_fragment_ignored(self):
        assert stream_key("https://x.com/a.mp4#t=10") == stream_key("https://x.com/a.mp4")

    def test_host_or_path_differs(self):
        assert stream_key("https://x.com/a.m3u8") != stream_key("https://x.com/b.m3u8")
        assert stream_key("https://x.com/a.m3u8") != stream_key("https://y.com/a.m3u8")

    def test_case_insensitive(self):
        assert stream_key("https://CDN.X.com/A.M3U8") == stream_key("https://cdn.x.com/a.m3u8")


class TestExtract:
    def test_ad_trailer_excluded(self):
        html = (
            '<script>var a="https://cdn.x.com/hls/main.m3u8";'
            'var b="https://cdn.x.com/hls/trailer.m3u8";'
            'var c="https://cdn.x.com/ads/blank.mp4"</script>'
        )
        out = extract_stream_urls(html)
        assert out == ["https://cdn.x.com/hls/main.m3u8"]

    def test_plain_mp4_kept(self):
        assert extract_stream_urls("src: 'https://x.com/media/ep1.mp4'") == [
            "https://x.com/media/ep1.mp4"
        ]

    def test_player_api_wrapper_rejected_nested_direct_kept(self):
        """播放器接口整串（path 非 .m3u8）排除；其 url= 参数里的真流直链保留。

        cz4k 类站实测坑：py.php?...&url=https://cdn/1.m3u8 被正则整串匹配，
        整串当流下载 → 必失败；真流被吞。
        """
        player = (
            "https://plaa.py1080p.com:8181/player/py.php"
            "?code=cs&if=l&url=https://m3hls3.pxxxojo.com/1.m3u8"
        )
        out = extract_stream_urls(player)
        assert player not in out
        assert out == ["https://m3hls3.pxxxojo.com/1.m3u8"]

    def test_player_api_only_yields_nothing(self):
        """播放器接口 URL 没嵌套可提取的流 → 不产出任何条目。"""
        assert extract_stream_urls(
            "GET https://host/player/py.php?code=cs&if=l&id=1"
        ) == []

    def test_m3u8_with_query_kept(self):
        """扩展名后带 query/fragment 的直链仍算流（path 校验只看 path 段）。"""
        assert extract_stream_urls(
            "https://cdn.x.com/hls/main.m3u8?sign=ab#frag"
        ) == ["https://cdn.x.com/hls/main.m3u8?sign=ab#frag"]


class TestDedupe:
    def test_cross_page_same_stream_one_entry(self):
        """跨页去重（R10）：签名参数不同的同一 m3u8 只留首见完整 URL。"""
        urls = [
            "https://cdn.x.com/v/index.m3u8?expires=1&sign=aa",
            "https://cdn.x.com/v/index.m3u8?expires=2&sign=bb",
            "https://cdn.x.com/v/index.m3u8?expires=3&sign=cc",
        ]
        out = dedupe_streams(urls)
        assert len(out) == 1
        assert out[0] == urls[0]  # 保留首见（带原签名，可直接下载）

    def test_distinct_streams_kept(self):
        urls = [
            "https://cdn.x.com/v/1.m3u8?sign=a",
            "https://cdn.x.com/v/2.m3u8?sign=b",
        ]
        assert dedupe_streams(urls) == urls


class TestPreferMain:
    def test_sub_dropped_when_main_present(self):
        """主/子列表并存 → 只保留主列表（§4.3 第一行）。"""
        urls = [
            "https://cdn.x.com/hls/640x360/video.m3u8",
            "https://cdn.x.com/hls/playlist.m3u8",
            "https://cdn.x.com/hls/1280x720/video.m3u8",
        ]
        assert prefer_main_streams(urls) == ["https://cdn.x.com/hls/playlist.m3u8"]

    def test_sub_only_kept(self):
        urls = ["https://cdn.x.com/hls/640x360/video.m3u8"]
        assert prefer_main_streams(urls) == urls

    def test_mp4_untouched(self):
        urls = ["https://cdn.x.com/media/a.mp4", "https://cdn.x.com/media/b.mp4"]
        assert prefer_main_streams(urls) == urls

    def test_empty(self):
        assert prefer_main_streams([]) == []
