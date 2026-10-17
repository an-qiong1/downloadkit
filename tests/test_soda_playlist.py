"""汽水歌单解析单元测试"""
import asyncio
import builtins
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from downloadkit.platforms.soda import (
    _extract_playlist_id,
    _find_track_id,
    _extract_audition_url,
)


# ============================ 汽水歌单 URL 提取 ============================

class TestSodaPlaylistId:
    def test_short_url(self):
        result = asyncio.run(_extract_playlist_id("https://qishui.douyin.com/s/abc123xyz"))
        # 短链接重定向可能失败（abc123xyz 是假 ID），兜底返回短码本身
        assert result == "abc123xyz"

    def test_full_url_with_query(self):
        url = "https://www.douyin.com/qishui/?playlist_id=xyz789&foo=bar"
        result = asyncio.run(_extract_playlist_id(url))
        assert result == "xyz789"

    def test_no_match(self):
        result = asyncio.run(_extract_playlist_id("https://example.com/"))
        assert result is None

    def test_empty(self):
        result = asyncio.run(_extract_playlist_id(""))
        assert result is None


# ============================ 汽水搜索匹配 ============================

class TestSodaSearchMatch:
    def test_exact_title_and_artist(self):
        items = [
            {"entity": {"track": {"id": "111", "name": "晴天", "artists": [{"name": "周杰伦"}]}}},
            {"entity": {"track": {"id": "222", "name": "晴天", "artists": [{"name": "其他歌手"}]}}},
        ]
        assert _find_track_id(items, "晴天", "周杰伦") == "111"

    def test_title_only_match(self):
        items = [
            {"entity": {"track": {"id": "111", "name": "晴天", "artists": [{"name": "周杰伦"}]}}},
        ]
        assert _find_track_id(items, "晴天", "未知") == "111"

    def test_multi_artist(self):
        items = [
            {"entity": {"track": {"id": "ABC", "name": "稻香", "artists": [{"name": "周杰伦"}, {"name": "洪敬尧"}]}}},
        ]
        assert _find_track_id(items, "稻香", "周杰伦") == "ABC"

    def test_empty_items(self):
        assert _find_track_id([], "晴天", "周杰伦") is None

    def test_fallback_first(self):
        items = [
            {"entity": {"track": {"id": "FIRST", "name": "无关歌曲", "artists": [{"name": "某人"}]}}},
        ]
        assert _find_track_id(items, "晴天", "周杰伦") == "FIRST"


# ============================ 分享页 audition_url 提取 ============================

class TestSodaAuditionUrl:
    def test_extract_from_router_data(self):
        html = '''
        <script>_ROUTER_DATA = {"loaderData": {"track_page": {"audioWithLyricsOption": {"url": "https://example.com/song.mp4"}}}};</script>
        '''
        result = _extract_audition_url(html, "123")
        assert result == "https://example.com/song.mp4"

    def test_extract_url_with_escape_sequences(self):
        html = '''
        <script>_ROUTER_DATA = {"loaderData": {"track_page": {"audioWithLyricsOption": {"url": "https://example.com/a%3Db/c%7Cd"}}}};</script>
        '''
        result = _extract_audition_url(html, "123")
        assert result == "https://example.com/a=b/c|d"

    def test_no_router_data(self):
        assert _extract_audition_url("<html>no data</html>", "123") is None

    def test_empty_html(self):
        assert _extract_audition_url("", "123") is None

    def test_url_without_http_prefix(self):
        html = '''
        <script>_ROUTER_DATA = {"loaderData": {"track_page": {"audioWithLyricsOption": {"url": "/relative/path"}}}};</script>
        '''
        assert _extract_audition_url(html, "123") is None

    # --- 回归：json_repair 缺失（打包 exe / 干净 venv 的实际情况） ---

    @staticmethod
    def _block_json_repair(monkeypatch):
        real_import = builtins.__import__

        def _no_json_repair(name, *args, **kwargs):
            if name == "json_repair":
                raise ImportError("No module named 'json_repair'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_json_repair)

    def test_extract_without_json_repair(self, monkeypatch):
        """没有 json_repair 也必须能解析 —— 标准库 json 优先。

        历史 bug（2026-10-17）：soda 在函数里 `import json_repair`，而它从未写进
        pyproject 依赖，venv 和打包 exe 中都不存在 → ModuleNotFoundError 被外层
        `except Exception` 静默吞掉 → 「打包版汽水 100% 拿不到下载链接」。
        """
        self._block_json_repair(monkeypatch)
        html = ('<script>_ROUTER_DATA = {"loaderData": {"track_page": '
                '{"audioWithLyricsOption": {"url": "https://example.com/song.mp4"}}}};</script>')
        assert _extract_audition_url(html, "123") == "https://example.com/song.mp4"

    def test_broken_json_without_json_repair_returns_none(self, monkeypatch):
        """损坏的 _ROUTER_DATA + 无 json_repair → 返回 None，不能抛异常。"""
        self._block_json_repair(monkeypatch)
        html = '<script>_ROUTER_DATA = {"loaderData": {broken};</script>'
        assert _extract_audition_url(html, "123") is None
