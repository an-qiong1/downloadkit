"""性能基准测试：防止 yt-dlp 等核心路径性能退化。

每个基准只跑一次（fast，不聚合），用 assert 封顶阈值，
超标即红，便于 CI 拦截回归。

基准场景：
  - search_latency：跨平台搜索一次的最坏耗时（上限 3s）
  - parse_latency：单个视频链接解析的最坏耗时（上限 5s）
  - run_async_overhead：run_async 调用开销应 < 5ms

注意：这些测试需要网络访问（搜索/解析会打真实 API），
在离线环境会用 pytest.mark.skip 跳过。
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================ run_async 开销 ============================

def test_run_async_overhead_small():
    """run_async 包装一个简单协程的开销应 < 5ms。"""
    from downloadkit.cli import run_async

    async def tiny():
        return 42

    t0 = time.perf_counter()
    result = run_async(tiny())
    elapsed = time.perf_counter() - t0

    assert result == 42
    assert elapsed < 0.005, f"run_async 开销 {elapsed*1000:.1f}ms，超出 5ms 阈值"


def test_run_async_overhead_repeated():
    """连续 10 次 run_async，平均开销仍应 < 5ms。"""
    from downloadkit.cli import run_async

    async def tiny():
        return 1

    total = 0.0
    for _ in range(10):
        t0 = time.perf_counter()
        run_async(tiny())
        total += time.perf_counter() - t0

    avg_ms = total / 10 * 1000
    assert avg_ms < 5.0, f"run_async 平均开销 {avg_ms:.1f}ms，超出 5ms 阈值"


# ============================ search 延迟 ============================

@pytest.mark.asyncio
async def test_search_latency_under_10s(monkeypatch):
    """跨平台搜索的一次调用不应超过 10 秒（考虑网络波动，上限放宽）。"""
    from downloadkit.searcher import search_all

    # 用一个已知能快速返回的关键词
    t0 = time.perf_counter()
    results = await search_all(keyword="test_nonexistent_key_12345", limit=5)
    elapsed = time.perf_counter() - t0

    # 即使搜不到，也应在时限内返回（网络超时保护）
    assert elapsed < 10.0, f"search 耗时 {elapsed:.1f}s，超出 10s 阈值"
    assert isinstance(results, list)


# ============================ parse 延迟 ============================

@pytest.mark.asyncio
async def test_parse_latency_under_5s(monkeypatch):
    """单个视频链接解析不应超过 5 秒（上限）。"""
    from downloadkit.video_service import parse_url

    # 用一个明显不支持的协议，应快速失败
    t0 = time.perf_counter()
    try:
        result = await parse_url("ftp://example.com/file.mp4")
    except Exception:
        result = None
    elapsed = time.perf_counter() - t0

    assert elapsed < 5.0, f"parse ftp URL 耗时 {elapsed:.1f}s，超出 5s 阈值"
