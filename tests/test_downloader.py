#!/usr/bin/env python3
"""
下载模块测试用例
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from downloadkit.downloader import download_song
from downloadkit.platforms.base import SongInfo


class TestDownloadSong:
    """歌曲下载测试"""
    
    def test_song_info_creation(self):
        """测试SongInfo数据结构"""
        song = SongInfo(
            title="测试歌曲",
            artist="测试歌手",
            platform="netease",
            song_id="12345"
        )
        assert song.title == "测试歌曲"
        assert song.artist == "测试歌手"
        assert song.platform == "netease"
        assert song.song_id == "12345"
    
    @pytest.mark.asyncio
    async def test_download_song_cancelled(self):
        """测试下载取消"""
        song = SongInfo(title="test", artist="test", platform="test", song_id="1")
        
        with patch('downloadkit.downloader.download_queue') as mock_queue:
            mock_queue.is_cancelled.return_value = True
            
            with pytest.raises(Exception):
                await download_song(song, task_id="test-task")
    
    @pytest.mark.asyncio
    async def test_download_song_paused_then_cancelled(self):
        """测试下载暂停后取消"""
        song = SongInfo(title="test", artist="test", platform="test", song_id="1")
        
        with patch('downloadkit.downloader.download_queue') as mock_queue:
            # 第一次检查暂停，第二次检查取消
            mock_queue.is_paused.side_effect = [True, False]
            mock_queue.is_cancelled.side_effect = [False, True]
            
            with pytest.raises(Exception):
                await download_song(song, task_id="test-task")


class TestDownloaderIntegration:
    """下载模块集成测试"""
    
    def test_downloader_import(self):
        """测试downloader模块可以正常导入"""
        from downloadkit import downloader
        assert hasattr(downloader, 'download_song')
    
    def test_downloader_has_required_functions(self):
        """测试downloader模块包含必要的函数"""
        from downloadkit import downloader
        assert callable(downloader.download_song)


class TestEmptyArtifactCleanup:
    """取消/失败后清理 0 字节产物空壳（2026-10-17 打包版实测回归）

    _stream_download 先 open(wb) 创建文件再流式写入；若在写出第一个
    字节前被取消或失败，磁盘上留下一个 0 字节 .mp3 —— 文件列表里显示成
    一首能看见、播不了的假歌。空壳对续传也无价值（续传看已有字节数，
    0 即从头下），download_song 失败/取消时必须清掉；非 0 的半截文件
    必须保留（那是同源续传的依据）。
    """

    def test_drop_empty_artifact_removes_zero_byte(self, tmp_path):
        from downloadkit.downloader import _drop_empty_artifact
        f = tmp_path / "歌 - 歌手.mp3"
        f.write_bytes(b"")  # 0 字节空壳
        _drop_empty_artifact(f)
        assert not f.exists(), "0 字节空壳没被清掉 → 文件列表会显示假歌"

    def test_drop_empty_artifact_keeps_partial(self, tmp_path):
        """非 0 半截文件必须保留（续传依据）"""
        from downloadkit.downloader import _drop_empty_artifact
        f = tmp_path / "歌 - 歌手.mp3"
        f.write_bytes(b"ID3xxx")  # 已有字节
        _drop_empty_artifact(f)
        assert f.exists(), "误删了半截文件 → 断点续传失效"
        assert f.stat().st_size == 6

    def test_drop_empty_artifact_missing_is_noop(self, tmp_path):
        from downloadkit.downloader import _drop_empty_artifact
        _drop_empty_artifact(tmp_path / "不存在.mp3")  # 不该抛

    @pytest.mark.asyncio
    async def test_download_song_all_fail_cleans_empty(self, tmp_path):
        """整条链都失败 → 不留空壳，且 download_song 返回 None"""
        from downloadkit.downloader import download_song
        from downloadkit.platforms.base import SongInfo
        song = SongInfo(title="不存在歌", artist="不存在人",
                        platform="soda", song_id="")

        # 全链失败：_get_download_url 返 None，各级 search 都抛，产物不落
        async def _boom(*a, **k):
            raise RuntimeError("无源")
        with patch('downloadkit.downloader._get_download_url',
                   new=AsyncMock(return_value=None)), \
             patch('downloadkit.downloader.itzo_search', new=_boom), \
             patch('downloadkit.downloader.gequbao_search', new=_boom), \
             patch('downloadkit.downloader.migu_search', new=_boom), \
             patch('downloadkit.downloader.kuwo_search', new=_boom), \
             patch('downloadkit.downloader.kugou_search', new=_boom), \
             patch('downloadkit.downloader.soda_search', new=_boom), \
             patch('downloadkit.downloader._download_via_ytdlp', new=_boom):
            r = await download_song(song, output_dir=str(tmp_path))

        assert r is None
        # 关键：失败后不许留下 0 字节空壳
        leftover = list(tmp_path.glob("*.mp3"))
        assert leftover == [], f"失败仍留产物: {[p.name for p in leftover]}"


class TestPreviewInterception:
    """P0-2 试听片段拦截（2026-10-18，基于 T3 实测数据设计）

    T3 368 首里有 3 首版权曲源侧只给 5-6 秒试听（≈83 KB，合法 MP3 魔数），
    旧逻辑"是 MP3 就接受"让它们伪装成下载成功落盘。现在 _stream_download
    收尾时按体积启发式判试听：命中则删除产物、本级算失败、链继续试下一级。
    """

    def test_preview_83kb_without_duration(self, tmp_path):
        """无时长信息：83 KB（T3 实测试听体量）判试听"""
        from downloadkit.downloader import _looks_like_preview
        f = tmp_path / "x.mp3"
        f.write_bytes(b"ID3" + b"\0" * 80_000)
        assert _looks_like_preview(f) is True

    def test_full_song_not_preview(self, tmp_path):
        """完整歌（3.3 MB，T3 平均体量）不误杀"""
        from downloadkit.downloader import _looks_like_preview
        f = tmp_path / "x.mp3"
        f.write_bytes(b"ID3" + b"\0" * 3_300_000)
        assert _looks_like_preview(f) is False
        assert _looks_like_preview(f, duration_sec=269) is False

    def test_duration_ratio_catches_bigger_preview(self, tmp_path):
        """时长判据抓得住超过 300KB 的试听：30s 片段 vs 269s 全曲

        期望 ≈ 269×16KB ≈ 4.3MB，实际 30s×16KB ≈ 480KB < 20% → 试听。
        没有时长信息时 480KB > 300KB 兜底线，会放行——两条判据互补。
        """
        from downloadkit.downloader import _looks_like_preview
        f = tmp_path / "x.mp3"
        f.write_bytes(b"ID3" + b"\0" * 480_000)
        assert _looks_like_preview(f, duration_sec=269) is True
        assert _looks_like_preview(f) is False, "无时长时不该误杀"

    def test_unknown_duration_uses_absolute_floor(self, tmp_path):
        """duration=0（歌单没给时长）只走绝对阈值，不拿比例误杀短歌"""
        from downloadkit.downloader import _looks_like_preview
        f = tmp_path / "x.mp3"
        f.write_bytes(b"ID3" + b"\0" * 500_000)  # 500KB
        assert _looks_like_preview(f, duration_sec=0) is False

    def test_zero_byte_is_preview(self, tmp_path):
        from downloadkit.downloader import _looks_like_preview
        f = tmp_path / "x.mp3"
        f.write_bytes(b"")
        assert _looks_like_preview(f, duration_sec=200) is True

    def test_missing_file_not_preview(self, tmp_path):
        from downloadkit.downloader import _looks_like_preview
        assert _looks_like_preview(tmp_path / "nope.mp3") is False

    @pytest.mark.asyncio
    async def test_stream_download_rejects_preview_and_deletes(self, tmp_path, monkeypatch):
        """_stream_download 命中试听判据 → 删产物、返回 False（链继续下一级）"""
        import httpx
        from downloadkit import downloader

        target = tmp_path / "歌 - 歌手.mp3"

        class _FakeResp:
            status_code = 200
            headers = {"content-type": "audio/mpeg"}

            def raise_for_status(self):  # 真实 httpx 里就是同步方法
                pass

            async def aiter_bytes(self, chunk_size=None):
                # 合法 MP3 头 + 试听体量（83KB）
                yield b"ID3" + b"\0" * (83_000 - 3)

        class _Ctx:
            async def __aenter__(self):
                return _FakeResp()
            async def __aexit__(self, *a):
                return False

        class _FakeClient:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            def stream(self, method, url):
                return _Ctx()

        monkeypatch.setattr(downloader.httpx, "AsyncClient", _FakeClient)

        ok = await downloader._stream_download("https://x/y.mp3", target,
                                               duration_sec=269)
        assert ok is False, "试听必须判为本级失败"
        assert not target.exists(), "试听产物必须删除，不许伪装成下载成功落盘"

    @pytest.mark.asyncio
    async def test_chain_rejects_preview_then_accepts_full_song(self, tmp_path,
                                                                monkeypatch):
        """整链行为：第一级给试听 → 判失败让位 → 第二级完整歌成功落盘

        这是拦截的设计目的本身（旧逻辑第一级 83KB 就直接"下载成功"）。
        体量按 T3 实测：试听 ≈83KB、完整歌平均 3.3MB；时长 269s 的比例
        判据下限 ≈862KB，所以"完整歌"给 3.2MB 不会被误伤。
        """
        from downloadkit import downloader
        from downloadkit.platforms.base import SongInfo

        async def _preview_url(song):
            return "https://s1/preview.mp3"

        async def _full_search(*a, **k):
            return "https://s2/full.mp3"

        async def _none_search(*a, **k):
            return None

        async def _no_ytdlp(song, filepath):
            return None

        async def _no_enrich(song):
            return None

        def _no_tags(*a, **k):
            return None

        class _Resp:
            status_code = 200
            headers = {"content-type": "audio/mpeg"}

            def __init__(self, url):
                self.payload = (b"ID3" + b"\0" * (83_000 - 3)
                                if "preview" in url
                                else b"ID3" + b"\0" * (3_200_000 - 3))

            def raise_for_status(self):
                pass

            async def aiter_bytes(self, chunk_size=None):
                for i in range(0, len(self.payload), 65536):
                    yield self.payload[i:i + 65536]

        class _Ctx:
            def __init__(self, resp):
                self._r = resp

            async def __aenter__(self):
                return self._r

            async def __aexit__(self, *a):
                return False

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url):
                return _Ctx(_Resp(url))

        monkeypatch.setattr(downloader, "_get_download_url", _preview_url)
        monkeypatch.setattr(downloader, "itzo_search", _full_search)
        for name in ("gequbao_search", "migu_search", "kuwo_search",
                     "kugou_search", "soda_search"):
            monkeypatch.setattr(downloader, name, _none_search)
        monkeypatch.setattr(downloader, "_download_via_ytdlp", _no_ytdlp)
        monkeypatch.setattr(downloader, "enrich_metadata", _no_enrich)
        monkeypatch.setattr(downloader, "write_tags", _no_tags)
        monkeypatch.setattr(downloader.httpx, "AsyncClient", _Client)

        song = SongInfo(title="给你一瓶魔法药水", artist="告五人",
                        platform="soda", song_id="x", duration=269)
        r = await downloader.download_song(song, output_dir=str(tmp_path))

        assert r is not None, "第二级完整歌应成功（试听被拒后链要继续往下走）"
        assert r.exists() and r.stat().st_size == 3_200_000, \
            "落盘的必须是完整歌产物，不是被删剩的试听"


class TestCancelSignalPropagation:
    """取消/暂停信号不许被兜底链逐级 except 吞掉（2026-10-18 P0-1 验收暴露）

    验收日志实锤的缺陷：取消后任务不立即停，而是走完剩余所有级——
      10:44:47 [soda] Error: 下载已取消      ← 本级 CancelException 被吞
      10:44:47 [yt-dlp] Searching...         ← 已取消的任务还去起 yt-dlp！
    每级 `_stream_download` 抛的 CancelException/PauseException 被下一步的
    `except Exception` 当"本级源失败"继续往下走，最终整链耗尽记成 failed。
    后果：取消响应慢 20-40s/首（yt-dlp 子进程）、批统计里 cancelled 被
    错记成 failed、白烧 API 调用。
    """

    @pytest.mark.asyncio
    async def test_cancel_stops_chain_at_first_stream(self, tmp_path, monkeypatch):
        from downloadkit import downloader
        from downloadkit.exceptions import CancelException
        from downloadkit.platforms.base import SongInfo

        later_calls = []

        async def _no_direct(song):
            return None  # Step 1 无直链，从 Step 2 起链

        async def _cancel_stream(url, filepath, task_id=None, duration_sec=0):
            raise CancelException("下载已取消")

        async def _itzo_hit(*a, **k):
            return "https://x/itzo.mp3"  # Step 2 命中，_stream 抛取消

        def _mk_search(name):
            async def _s(*a, **k):
                later_calls.append(name)
                return None
            return _s

        async def _ytdlp(*a, **k):
            later_calls.append("yt-dlp")
            return None

        class _Q:
            def is_cancelled(self, t):
                return False

            def is_paused(self, t):
                return False

            def update_progress(self, *a, **k):
                pass

        monkeypatch.setattr(downloader, "download_queue", _Q())
        monkeypatch.setattr(downloader, "_get_download_url", _no_direct)
        monkeypatch.setattr(downloader, "_stream_download", _cancel_stream)
        monkeypatch.setattr(downloader, "itzo_search", _itzo_hit)
        for name in ("gequbao", "migu", "kuwo", "kugou", "soda"):
            monkeypatch.setattr(downloader, f"{name}_search",
                                _mk_search(name))
        monkeypatch.setattr(downloader, "_download_via_ytdlp", _ytdlp)

        song = SongInfo(title="歌", artist="手", platform="soda", song_id="1")
        import pytest as _pt
        with _pt.raises(CancelException):
            await downloader.download_song(song, task_id="t1",
                                           output_dir=str(tmp_path))

        assert later_calls == [], (
            f"取消信号被吞，链还继续走了 {later_calls} —— 应第一处取消即中止"
        )

    @pytest.mark.asyncio
    async def test_pause_stops_chain_at_first_stream(self, tmp_path, monkeypatch):
        """暂停同理：不能被当本级失败继续往下烧下一级"""
        from downloadkit import downloader
        from downloadkit.exceptions import PauseException
        from downloadkit.platforms.base import SongInfo

        later_calls = []

        async def _no_direct(song):
            return None

        async def _pause_stream(url, filepath, task_id=None, duration_sec=0):
            raise PauseException("下载已暂停")

        async def _itzo_hit(*a, **k):
            return "https://x/itzo.mp3"

        def _mk_search(name):
            async def _s(*a, **k):
                later_calls.append(name)
                return None
            return _s

        class _Q:
            def is_cancelled(self, t):
                return False

            def is_paused(self, t):
                return False

            def update_progress(self, *a, **k):
                pass

        monkeypatch.setattr(downloader, "download_queue", _Q())
        monkeypatch.setattr(downloader, "_get_download_url", _no_direct)
        monkeypatch.setattr(downloader, "_stream_download", _pause_stream)
        monkeypatch.setattr(downloader, "itzo_search", _itzo_hit)
        for name in ("gequbao", "migu", "kuwo", "kugou", "soda"):
            monkeypatch.setattr(downloader, f"{name}_search",
                                _mk_search(name))

        async def _ytdlp(*a, **k):
            later_calls.append("yt-dlp")
            return None

        monkeypatch.setattr(downloader, "_download_via_ytdlp", _ytdlp)

        song = SongInfo(title="歌", artist="手", platform="soda", song_id="1")
        import pytest as _pt
        with _pt.raises(PauseException):
            await downloader.download_song(song, task_id="t2",
                                           output_dir=str(tmp_path))
        assert later_calls == []




if __name__ == '__main__':
    pytest.main([__file__, '-v'])
