"""服务端 /api/history/* 端点单元测试

覆盖 5 个端点：
  GET    /api/history              列表（分页）
  POST   /api/history/search       搜索
  DELETE /api/history/{id}         删除
  POST   /api/history/clear        清空
  GET    /api/history/count        总数

测试策略：直接 import route 函数，monkeypatch download_history 对象，
不启动真实服务。参数校验走 FastAPI 类型注入，业务逻辑走 mocked 模块。
每个测试用独立实例，避免状态污染。
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import (
    api_history_list,
    api_history_search,
    api_history_delete,
    api_history_clear,
    api_history_count,
)
from downloadkit.history import HistoryRecord


# ---------- fixture：可替换的 fake download_history ----------

def _make_fake(records=None):
    """返回一个伪造的 DownloadHistory 实例，支持常见操作。"""
    records = list(records) if records else []

    class Fake:
        def get_records(self, limit=50, offset=0):
            return list(records[offset:offset + limit])

        def search_records(self, keyword):
            kw = keyword.strip().lower()
            return [r for r in records
                    if kw in (r.title or "").lower()
                    or kw in (r.author or "").lower()]

        def delete_record(self, record_id):
            records[:] = [r for r in records if r.id != record_id]

        def clear_history(self):
            records[:] = []

        def get_total_count(self):
            return len(records)

    return Fake()


_Sample = [
    HistoryRecord(id=1, url="https://example.com/1", platform="douyin",
                  title="晴天", author="周杰伦", cover="",
                  file_path="/tmp/晴天.mp3", file_size=5242880,
                  downloaded_at="2026-10-15 10:00:00"),
    HistoryRecord(id=2, url="https://example.com/2", platform="bilibili",
                  title="某视频", author="UP主", cover="",
                  file_path="/tmp/某视频.mp4", file_size=104857600,
                  downloaded_at="2026-10-14 08:30:00"),
]


# ============================ list ============================

@pytest.mark.asyncio
async def test_list_returns_records(monkeypatch):
    monkeypatch.setattr("server.download_history", _make_fake(_Sample))
    result = await api_history_list()
    assert len(result) == 2
    assert result[0]["title"] == "晴天"
    assert result[1]["title"] == "某视频"


@pytest.mark.asyncio
async def test_list_pagination(monkeypatch):
    fh = _make_fake(_Sample)
    monkeypatch.setattr("server.download_history", fh)
    result = await api_history_list(limit=1, offset=0)
    assert len(result) == 1
    assert result[0]["title"] == "晴天"

    result = await api_history_list(limit=1, offset=1)
    assert len(result) == 1
    assert result[0]["title"] == "某视频"


@pytest.mark.asyncio
async def test_list_empty_returns_empty(monkeypatch):
    monkeypatch.setattr("server.download_history", _make_fake([]))
    result = await api_history_list()
    assert result == []


@pytest.mark.asyncio
async def test_list_negative_params_raise_400():
    with pytest.raises(HTTPException) as exc:
        await api_history_list(limit=-1, offset=0)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        await api_history_list(limit=10, offset=-5)
    assert exc.value.status_code == 400


# ============================ search ============================

@pytest.mark.asyncio
async def test_search_by_title(monkeypatch):
    monkeypatch.setattr("server.download_history", _make_fake(_Sample))
    result = await api_history_search(keyword="晴天")
    assert len(result) == 1
    assert result[0]["title"] == "晴天"


@pytest.mark.asyncio
async def test_search_by_author(monkeypatch):
    monkeypatch.setattr("server.download_history", _make_fake(_Sample))
    result = await api_history_search(keyword="UP主")
    assert len(result) == 1
    assert result[0]["author"] == "UP主"


@pytest.mark.asyncio
async def test_search_no_match(monkeypatch):
    monkeypatch.setattr("server.download_history", _make_fake(_Sample))
    result = await api_history_search(keyword="不存在的标题")
    assert result == []


@pytest.mark.asyncio
async def test_search_empty_keyword_raise_400():
    with pytest.raises(HTTPException) as exc:
        await api_history_search(keyword="")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        await api_history_search(keyword="   ")
    assert exc.value.status_code == 400


# ============================ delete ============================

@pytest.mark.asyncio
async def test_delete_existing_record(monkeypatch):
    fh = _make_fake([
        HistoryRecord(id=1, url="u", platform="p", title="t", author="a",
                      cover="", file_path="", file_size=0, downloaded_at="now"),
    ])
    monkeypatch.setattr("server.download_history", fh)
    result = await api_history_delete(record_id=1)
    assert result == {"status": "deleted"}
    assert fh.get_total_count() == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_does_not_raise(monkeypatch):
    """删除不存在的 ID 不报错，静默忽略（与原实现一致）。"""
    fh = _make_fake([])
    monkeypatch.setattr("server.download_history", fh)
    result = await api_history_delete(record_id=999)
    assert result == {"status": "deleted"}
    assert fh.get_total_count() == 0


# ============================ clear ============================

@pytest.mark.asyncio
async def test_clear_removes_all(monkeypatch):
    fh = _make_fake(_Sample)
    monkeypatch.setattr("server.download_history", fh)
    result = await api_history_clear()
    assert result == {"status": "cleared"}
    assert fh.get_total_count() == 0


@pytest.mark.asyncio
async def test_clear_empty_is_ok(monkeypatch):
    monkeypatch.setattr("server.download_history", _make_fake([]))
    result = await api_history_clear()
    assert result == {"status": "cleared"}


# ============================ count ============================

@pytest.mark.asyncio
async def test_count_returns_total(monkeypatch):
    monkeypatch.setattr("server.download_history", _make_fake(_Sample))
    result = await api_history_count()
    assert result == {"count": 2}


@pytest.mark.asyncio
async def test_count_empty_is_zero(monkeypatch):
    monkeypatch.setattr("server.download_history", _make_fake([]))
    result = await api_history_count()
    assert result == {"count": 0}


# ============================ 路由不冲突 ============================

def test_history_routes_not_shadowed_by_param_route():
    """确保 /api/history/search、/api/history/clear、/api/history/count
    不被 /api/history/{record_id} 参数路由先匹配。"""
    from server import app

    def first_match(method, url):
        for route in app.routes:
            methods = getattr(route, "methods", None)
            if methods and method not in methods:
                continue
            regex = getattr(route, "path_regex", None)
            if regex and regex.match(url):
                return route.path
        return None

    assert first_match("GET", "/api/history") == "/api/history"
    assert first_match("POST", "/api/history/search") == "/api/history/search"
    assert first_match("POST", "/api/history/clear") == "/api/history/clear"
    assert first_match("GET", "/api/history/count") == "/api/history/count"
    assert first_match("DELETE", "/api/history/42") == "/api/history/{record_id}"
