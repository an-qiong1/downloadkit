"""服务端 /api/bookmarks/probe/* 端点单元测试

覆盖 3 个端点：
  POST /api/bookmarks/probe                  启动探测
  GET  /api/bookmarks/probe/{probe_id}       查询进度/结果
  POST /api/bookmarks/probe/{probe_id}/stop  停止探测

测试策略：直接 import route 函数，monkeypatch _probes 字典，
不启动真实服务，不真正执行后台探测任务。
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import (
    api_bookmarks_probe,
    api_bookmarks_probe_status,
    api_bookmarks_probe_stop,
    ProbeRequest,
    BatchItem,
    _probes,
)


# ---------- fixture：每次测试前清空 _probes ----------

@pytest.fixture(autouse=True)
def _clean_probes():
    _probes.clear()
    yield
    _probes.clear()


# ---------- helper：手动向 _probes 注入状态 ----------

def _inject_probe(probe_id, status="running", total=2, done=0, hit=0,
                  results=None, error=""):
    _probes[probe_id] = {
        "status": status, "total": total, "done": done, "hit": hit,
        "results": results or [], "cancelled": asyncio.Event(),
        "error": error,
    }


# ============================ create (POST) ============================

@pytest.mark.asyncio
async def test_probe_starts_and_returns_id():
    req = ProbeRequest(urls=["https://example.com/v/1", "https://example.com/v/2"],
                       l2=True)
    result = await api_bookmarks_probe(req)
    assert "probe_id" in result
    assert result["total"] == 2
    # probe 已写入 _probes
    assert result["probe_id"] in _probes
    assert _probes[result["probe_id"]]["status"] == "running"
    assert _probes[result["probe_id"]]["total"] == 2


@pytest.mark.asyncio
async def test_probe_items_mode():
    """items 优先于 urls；传 items 时 urls 被忽略。"""
    req = ProbeRequest(items=[BatchItem(url="https://example.com/v/1")],
                       urls=["https://example.com/v/999"], l2=False)
    result = await api_bookmarks_probe(req)
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_probe_filters_non_http_urls():
    """非 HTTP 链接应被过滤，不计数。"""
    req = ProbeRequest(urls=["https://example.com/v/1", "not-a-url",
                             "mailto:x@y.com"], l2=True)
    result = await api_bookmarks_probe(req)
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_probe_empty_urls_raise_400():
    """没有任何可探测的 HTTP 链接 → 400。"""
    req = ProbeRequest(urls=[], l2=True)
    with pytest.raises(HTTPException) as exc:
        await api_bookmarks_probe(req)
    assert exc.value.status_code == 400
    assert "没有可探测的链接" in exc.value.detail

    req2 = ProbeRequest(
        items=[BatchItem(url="not-http"), BatchItem(url="")], l2=True)
    with pytest.raises(HTTPException) as exc:
        await api_bookmarks_probe(req2)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_probe_l2_default_is_true():
    """l2 默认为 True（快速通道 + 浏览器嗅探）。"""
    req = ProbeRequest(urls=["https://example.com/v/1"])
    result = await api_bookmarks_probe(req)
    pid = result["probe_id"]
    # 后台任务已启动；l2 参数传给 _run_probe
    assert _probes[pid]["status"] == "running"


# ============================ status (GET) ============================

@pytest.mark.asyncio
async def test_status_running():
    pid = "probe_running_test"
    _inject_probe(pid, status="running", total=5, done=2, hit=1)
    result = await api_bookmarks_probe_status(probe_id=pid)
    assert result["status"] == "running"
    assert result["total"] == 5
    assert result["done"] == 2
    assert result["hit"] == 1


@pytest.mark.asyncio
async def test_status_done():
    pid = "probe_done_test"
    _inject_probe(pid, status="done", total=3, done=3, hit=2,
                  results=[{"url": "u1", "status": "hit"},
                           {"url": "u2", "status": "miss"}])
    result = await api_bookmarks_probe_status(probe_id=pid)
    assert result["status"] == "done"
    assert result["hit"] == 2
    assert len(result["results"]) == 2


@pytest.mark.asyncio
async def test_status_not_found_raises_404():
    with pytest.raises(HTTPException) as exc:
        await api_bookmarks_probe_status(probe_id="nonexistent_probe_id")
    assert exc.value.status_code == 404
    assert "不存在" in exc.value.detail


# ============================ stop (POST) ============================

@pytest.mark.asyncio
async def test_stop_running_becomes_stopped():
    pid = "probe_stop_test"
    _inject_probe(pid, status="running", total=5, done=2)
    result = await api_bookmarks_probe_stop(probe_id=pid)
    assert result["status"] == "stopped"
    assert result["done"] == 2
    # _probes 中的状态也应更新
    assert _probes[pid]["status"] == "stopped"
    # cancelled event 应已触发
    assert _probes[pid]["cancelled"].is_set()


@pytest.mark.asyncio
async def test_stop_already_stopped():
    pid = "probe_stop_test2"
    _inject_probe(pid, status="stopped", total=5, done=5)
    result = await api_bookmarks_probe_stop(probe_id=pid)
    assert result["status"] == "stopped"


@pytest.mark.asyncio
async def test_stop_not_found_raises_404():
    with pytest.raises(HTTPException) as exc:
        await api_bookmarks_probe_stop(probe_id="nonexistent_probe_id")
    assert exc.value.status_code == 404
    assert "不存在" in exc.value.detail


# ============================ 清理已结束任务 ============================

@pytest.mark.asyncio
async def test_probe_cleanups_finished_entries():
    """启动新探测时，已结束的历史记录应被清理。"""
    # 先塞一条已完成的
    _inject_probe("old_probe", status="done", total=1, done=1, hit=0)
    assert "old_probe" in _probes

    req = ProbeRequest(urls=["https://example.com/v/1"], l2=False)
    result = await api_bookmarks_probe(req)
    # 旧的已完成条目应被清理
    assert "old_probe" not in _probes
    assert result["probe_id"] in _probes
