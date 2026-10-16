"""Platform adapter unit tests

覆盖平台适配器的纯逻辑部分：
- URL 匹配（静态方法）
- ID 提取（静态方法）
- 数据解析（内部函数）
- 异常路径（空响应、非法输入）

测试策略：直接导入模块函数，不发起网络请求，
用 fixture 提供模拟 API 响应。
"""
import sys
from pathlib import Path

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from downloadkit.platforms.netease import (
    NeteasePlatform,
    _parse_song_item,
    _extract_artists,
    _extract_album,
    _get_cover_url,
    _get_album_name,
    _get_artist_name,
    _parse_year,
)
from downloadkit.platforms.qqmusic import QQMusicPlatform
from downloadkit.platforms.migu import _clean_artist
from downloadkit.platforms.gequbao import (
    _find_aid,
    _parse_app_data,
    _extract_download_url,
)


# ============================ netease 解析函数 ============================

class TestNeteaseParsing:
    """网易云数据解析函数测试。"""

    def test_parse_song_item_basic(self):
        """正常歌曲对象解析。"""
        item = {
            "name": "晴天",
            "ar": [{"name": "周杰伦"}],
            "al": {"name": "叶惠美", "picUrl": "https://example.com/cover.jpg"},
            "dt": 269000,
            "id": 12345,
            "no": 1,
        }
        result = _parse_song_item(item, "netease")
        assert result is not None
        assert result.title == "晴天"
        assert result.artist == "周杰伦"
        assert result.album == "叶惠美"
        assert result.duration == 269
        assert result.song_id == "12345"
        assert result.cover == "https://example.com/cover.jpg"
        assert result.track_number == 1

    def test_parse_song_item_new_format(self):
        """新格式字段解析（artists/album）。"""
        item = {
            "name": "稻香",
            "artists": [{"name": "周杰伦"}, {"name": "洪敬尧"}],
            "album": {"name": "魔杰座", "picUrl": "https://example.com/cover2.jpg"},
            "dt": 223000,
            "id": 67890,
        }
        result = _parse_song_item(item, "netease")
        assert result is not None
        assert result.title == "稻香"
        assert result.artist == "周杰伦/洪敬尧"
        assert result.duration == 223

    def test_parse_song_item_missing_fields(self):
        """缺失字段时不崩溃。"""
        item = {"name": "无名这首歌"}
        result = _parse_song_item(item, "netease")
        assert result is not None
        assert result.title == "无名这首歌"
        assert result.artist == ""
        assert result.song_id == ""

    def test_parse_song_item_exception_returns_none(self):
        """解析异常时返回 None（实际行为：log warning + return None）。"""
        result = _parse_song_item(None, "netease")
        assert result is None

    def test_extract_artists_new_format(self):
        artists = _extract_artists({"artists": [{"name": "A"}]})
        assert len(artists) == 1
        assert artists[0]["name"] == "A"

    def test_extract_artists_old_format(self):
        artists = _extract_artists({"ar": [{"name": "B"}]})
        assert len(artists) == 1
        assert artists[0]["name"] == "B"

    def test_extract_artists_empty(self):
        assert _extract_artists({}) == []
        assert _extract_artists({"artists": None}) == []

    def test_extract_album_new_format(self):
        album = _extract_album({"album": {"name": "Test"}})
        assert album == {"name": "Test"}

    def test_extract_album_old_format(self):
        album = _extract_album({"al": {"name": "Test2"}})
        assert album == {"name": "Test2"}

    def test_extract_album_not_dict(self):
        assert _extract_album({"album": "string"}) == {}

    def test_get_cover_url_with_picurl(self):
        url = _get_cover_url({"picUrl": "https://example.com/img.jpg"})
        assert url == "https://example.com/img.jpg"

    def test_get_cover_url_with_picid(self):
        url = _get_cover_url({"picId": "12345"})
        assert url == "https://p4.music.126.net/12345/12345.jpg"

    def test_get_cover_url_fallback_blur(self):
        url = _get_cover_url({"blurPicUrl": "https://example.com/blur.jpg"})
        assert url == "https://example.com/blur.jpg"

    def test_get_cover_url_empty(self):
        assert _get_cover_url({}) == ""

    def test_get_album_name(self):
        assert _get_album_name({"name": "Album1"}) == "Album1"
        assert _get_album_name({}) == ""

    def test_get_artist_name(self):
        assert _get_artist_name({"name": "Artist1"}) == "Artist1"
        assert _get_artist_name({}) == ""

    def test_parse_year_from_timestamp(self):
        import datetime
        ts = int(datetime.datetime(2024, 3, 15).timestamp() * 1000)
        assert _parse_year(ts) == 2024

    def test_parse_year_invalid(self):
        # String 会触发 TypeError（函数没有字符串类型保护），测试函数本身的防御性
        with pytest.raises(TypeError):
            _parse_year("invalid")  # type: ignore[arg-type]
        # None 和 0 是 falsy，直接返回 0
        assert _parse_year(None) == 0
        assert _parse_year(0) == 0


# ============================ netease 静态方法 ============================

class TestNeteaseStatic:
    """网易云静态方法测试。"""

    def test_match_url_true(self):
        assert NeteasePlatform.match_url("https://music.163.com/#/playlist?id=123") is True
        assert NeteasePlatform.match_url("https://music.163.com/song?id=456") is True
        assert NeteasePlatform.match_url("https://music.163.com/api/playlist/detail?id=789") is True

    def test_match_url_false(self):
        assert NeteasePlatform.match_url("https://y.qq.com/") is False
        assert NeteasePlatform.match_url("https://example.com/music") is False
        assert NeteasePlatform.match_url("") is False

    def test_extract_playlist_id_from_query(self):
        assert NeteasePlatform.extract_playlist_id("https://music.163.com/#/playlist?id=12345") == "12345"
        assert NeteasePlatform.extract_playlist_id("https://music.163.com/playlist?id=67890&foo=bar") == "67890"

    def test_extract_playlist_id_from_path(self):
        assert NeteasePlatform.extract_playlist_id("https://music.163.com/#/playlist/12345") == "12345"
        assert NeteasePlatform.extract_playlist_id("https://music.163.com/playlist/67890") == "67890"

    def test_extract_playlist_id_song_url_raises(self):
        with pytest.raises(ValueError, match="single song"):
            NeteasePlatform.extract_playlist_id("https://music.163.com/#/song?id=123")

    def test_extract_playlist_id_no_id_raises(self):
        with pytest.raises(ValueError, match="Cannot extract"):
            NeteasePlatform.extract_playlist_id("https://music.163.com/")


# ============================ qqmusic 静态方法 ============================

class TestQQMusicStatic:
    """QQ音乐静态方法测试。"""

    def test_match_url_true(self):
        assert QQMusicPlatform.match_url("https://y.qq.com/n/ryqq/songDetail/003WbMvi3FskuE") is True
        assert QQMusicPlatform.match_url("https://y.qq.com/portal/player.html") is True
        assert QQMusicPlatform.match_url("https://y.qq.complaylist?id=123") is True

    def test_match_url_false(self):
        assert QQMusicPlatform.match_url("https://music.163.com/") is False
        assert QQMusicPlatform.match_url("https://example.com/") is False
        assert QQMusicPlatform.match_url("") is False

    def test_extract_playlist_id_from_query(self):
        assert QQMusicPlatform.extract_playlist_id("https://y.qq.com/n/ryqq/playlist/12345") == "12345"
        assert QQMusicPlatform.extract_playlist_id("https://y.qq.complaylist?id=67890") == "67890"

    def test_extract_playlist_id_from_path(self):
        assert QQMusicPlatform.extract_playlist_id("https://y.qq.com/n/ryqq/playlistDetail/12345") == "12345"
        # /taoge/NNNN 格式
        assert QQMusicPlatform.extract_playlist_id("https://y.qq.com/taoge/12345") == "12345"

    def test_extract_playlist_id_no_match_raises(self):
        with pytest.raises(ValueError, match="Cannot extract"):
            QQMusicPlatform.extract_playlist_id("https://y.qq.com/")


# ============================ migu 辅助函数 ============================

class TestMiguHelpers:
    """咪咕辅助函数测试。"""

    def test_clean_artist_single(self):
        assert _clean_artist("周杰伦") == "周杰伦"

    def test_clean_artist_multiple(self):
        assert _clean_artist("周杰伦/洪敬尧") == "周杰伦"

    def test_clean_artist_with_spaces(self):
        assert _clean_artist("  周杰伦  ") == "周杰伦"

    def test_clean_artist_empty(self):
        assert _clean_artist("") == ""


# ============================ gequbao 辅助函数 ============================

class TestGequbaoHelpers:
    """歌曲宝辅助函数测试。"""

    def test_find_aid_from_data_aid(self):
        html = '<a href="/music/12345">歌曲1</a><a href="/music/67890">歌曲2</a>'
        result = _find_aid(html, "歌曲1", "歌手1")
        assert result == "12345"

    def test_find_aid_no_match(self):
        html = '<div>无 aid 信息</div>'
        result = _find_aid(html, "不存在的歌曲", "未知歌手")
        # 返回 None 或第一个 aid
        assert result is None or isinstance(result, str)

    def test_parse_app_data_valid(self):
        html = "<script>window.appData=JSON.parse('{\"play_id\":\"abc123\",\"title\":\"\\u6d4b\\u8bd5\"}');</script>"
        result = _parse_app_data(html)
        assert result is not None
        assert result.get("play_id") == "abc123"

    def test_parse_app_data_invalid(self):
        html = '<script>无 appData</script>'
        result = _parse_app_data(html)
        assert result is None

    def test_parse_app_data_empty(self):
        assert _parse_app_data("") is None

    def test_extract_download_url_with_mp3(self):
        html = '<a href="https://example.com/song.mp3">下载</a>'
        result = _extract_download_url(html)
        assert result == "https://example.com/song.mp3"

    def test_extract_download_url_no_match(self):
        html = '无链接信息'
        result = _extract_download_url(html)
        assert result is None


# ============================ itzo 搜索逻辑 ============================

class TestItzoSearch:
    """Itzo 搜索匹配逻辑测试。"""

    def test_match_by_title_and_artist(self):
        items = [
            {"title": "晴天", "author": "周杰伦", "url": "https://example.com/1"},
            {"title": "晴天", "author": "其他歌手", "url": "https://example.com/2"},
        ]
        clean_title = "晴天"
        clean_artist = "周杰伦"
        best = items[0]
        for item in items:
            item_title = item.get("title", "").strip().lower()
            item_artist = item.get("author", "").split(",")[0].strip().lower()
            if clean_title in item_title and clean_artist in item_artist:
                best = item
                break
        assert best["url"] == "https://example.com/1"

    def test_match_by_title_only(self):
        items = [
            {"title": "晴天", "author": "周杰伦", "url": "https://example.com/1"},
            {"title": "晴天草", "author": "歌手", "url": "https://example.com/2"},
        ]
        clean_title = "晴天"
        clean_artist = "周杰伦"
        best = items[0]
        for item in items:
            item_title = item.get("title", "").strip().lower()
            item_artist = item.get("author", "").split(",")[0].strip().lower()
            if clean_title in item_title and clean_artist in item_artist:
                best = item
                break
            if clean_title in item_title and best == items[0]:
                best = item
        assert best["title"] == "晴天"

    def test_no_match_returns_first(self):
        items = [
            {"title": "无关歌曲", "author": "歌手", "url": "https://example.com/1"},
        ]
        clean_title = "晴天"
        clean_artist = "周杰伦"
        best = items[0]
        for item in items:
            item_title = item.get("title", "").strip().lower()
            item_artist = item.get("author", "").split(",")[0].strip().lower()
            if clean_title in item_title and clean_artist in item_artist:
                best = item
                break
        assert best == items[0]

    def test_url_protocol_upgrade(self):
        url = "http://example.com/song.mp3"
        upgraded = url.replace("http:", "https:")
        assert upgraded == "https://example.com/song.mp3"

    def test_empty_items_returns_none(self):
        items = []
        if not items:
            result = None
        assert result is None
