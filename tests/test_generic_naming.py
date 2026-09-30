# -*- coding: utf-8 -*-
"""downloadkit.generic_video 命名单测：弱标题 / 剧名集数 / build_file_stem 优先级。"""
from downloadkit.generic_video import (
    build_file_stem,
    is_weak_title,
    parse_series_episode,
)

# ---------- 弱标题 ----------

def test_weak_titles():
    for t in ("", "  ", "playlist", "index", "master", "Playlist", "0",
              "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
              "https://cdn.x.com/a/playlist.m3u8"):
        assert is_weak_title(t) is True, t


def test_strong_titles():
    for t in ("师兄啊师兄 第01集", "凡人修仙传", "HTML5 Video", "第12话"):
        assert is_weak_title(t) is False, t


# ---------- 剧名集数 ----------

def test_series_episode_cn():
    assert parse_series_episode("师兄啊师兄 第01集-某站") == ("师兄啊师兄", "第01集")
    assert parse_series_episode("师兄啊师兄 第1集") == ("师兄啊师兄", "第01集")
    assert parse_series_episode("某剧 第12话") == ("某剧", "第12话")
    assert parse_series_episode("第103集") == ("", "第103集")
    assert parse_series_episode("凡人修仙传 EP12") == ("凡人修仙传", "第12集")
    assert parse_series_episode("斗罗大陆12集") == ("斗罗大陆", "第12集")


def test_series_episode_none():
    assert parse_series_episode("普通网页视频标题") == ("", "")
    assert parse_series_episode("") == ("", "")


# ---------- 文件名组装 ----------

def test_stem_episode_priority():
    """含集数的候选优先：书签标题有集数 → 剧名-第NN集"""
    assert build_file_stem(
        hint="师兄啊师兄 第01集",
        title="playlist",
        url="https://cdn.x.com/playlist.m3u8",
    ) == "师兄啊师兄-第01集"


def test_stem_title_beats_weak_hint():
    """hint 弱（追剧这种无集数标签）但解析标题带集数 → 用标题的集数"""
    assert build_file_stem(
        hint="好看视频",
        title="凡人修仙传 第12集-某某影视",
        url="https://a.com/x",
    ) == "凡人修仙传-第12集"


def test_stem_hint_wins_when_no_episode():
    """都无集数 → hint（用户意图）优先于解析标题"""
    assert build_file_stem(
        hint="我的收藏A",
        title="某个网页标题",
        url="https://a.com/x",
    ) == "我的收藏A"


def test_stem_title_when_no_hint():
    assert build_file_stem(title="网页标题", url="https://a.com/x") == "网页标题"


def test_stem_page_title_fallback():
    """yt-dlp 标题弱 → 用抓到的网页 <title>"""
    assert build_file_stem(
        hint="",
        title="playlist",
        page_title="某剧正片在线观看",
        url="https://a.com/play/1",
    ) == "某剧正片在线观看"


def test_stem_url_fallback_keeps_prefix():
    """全弱 → URL 末段 + web_ 前缀（保留既有行为）"""
    assert build_file_stem(
        hint="", title="playlist",
        url="https://cdn.x.com/abc/movie.m3u8",
    ) == "web_movie"
    assert build_file_stem(hint="", title="", url="") == "unknown"


def test_stem_sanitizable_and_trimmed():
    """长度截断 120、尾部空白/点清理（Windows 文件名兼容）"""
    long_title = "长" * 300
    assert len(build_file_stem(title=long_title)) <= 120
    assert build_file_stem(title="  标题  .  ") == "标题"
