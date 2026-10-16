"""服务端 /api/collections/* 端点单元测试

覆盖 6 个端点：
  GET    /api/collections                  列表
  POST   /api/collections                  新增
  GET    /api/collections/{id}             详情
  PUT    /api/collections/{id}             更新
  DELETE /api/collections/{id}             删除
  POST   /api/collections/{id}/refresh     刷新

测试策略：直接 import route 函数，monkeypatch downloadkit.collection 模块，
不启动真实服务。每个测试用独立实例，避免状态污染。
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import (
    api_collections_list,
    api_collections_create,
    api_collections_get,
    api_collections_update,
    api_collections_delete,
    api_collections_refresh,
    CreateCollectionRequest,
    UpdateCollectionRequest,
)


# ---------- fixture：可替换的 fake collection 模块 ----------

def _make_fake(collections=None, tracks_per=None):
    """返回伪造的 collection 模块替身，每次调用都是独立实例。

    collections: [{id, name, url, platform, auto_name, created_at, refreshed_at}]
    tracks_per:  每个集合默认曲目数（当 tracks 未指定时）
    """
    collections = list(collections) if collections else []
    tracks_per = tracks_per or 3

    # 深拷贝，避免共享可变状态
    store = []
    for c in collections:
        row = dict(c)
        if "tracks" not in row:
            row["tracks"] = [
                {"id": ti, "title": f"曲目{ti}", "artist": "歌手",
                 "album": "专辑", "song_id": f"sid{ti}",
                 "platform": "netease", "sort_order": ti - 1}
                for ti in range(1, tracks_per + 1)
            ]
        store.append(row)

    next_id = max((c["id"] for c in store), default=0) + 1

    class FakeModule:
        def list_collections(self):
            return [{"id": c["id"], "name": c["name"], "url": c["url"],
                     "platform": c["platform"], "song_count": len(c.get("tracks", [])),
                     "auto_name": c.get("auto_name", 1),
                     "created_at": c.get("created_at", ""),
                     "refreshed_at": c.get("refreshed_at", "")}
                    for c in store]

        def get_collection(self, collection_id):
            for c in store:
                if c["id"] == collection_id:
                    return c
            return None

        def create_collection(self, url, name=""):
            for c in store:
                if c["url"] == url:
                    raise ValueError(f"该歌单已收藏（ID: {c['id']}），请勿重复添加")
            nonlocal next_id
            cid = next_id
            next_id += 1
            new = {"id": cid, "name": name or "新收藏", "url": url,
                   "platform": "netease", "song_count": 3,
                   "auto_name": 1, "created_at": "", "refreshed_at": "",
                   "tracks": [
                       {"id": ti, "title": f"曲目{ti}", "artist": "歌手",
                        "album": "专辑", "song_id": f"sid{ti}",
                        "platform": "netease", "sort_order": ti - 1}
                       for ti in range(1, 4)
                   ]}
            store.append(new)
            return new

        def update_collection(self, collection_id, **kwargs):
            for c in store:
                if c["id"] == collection_id:
                    if "name" in kwargs:
                        c["name"] = kwargs["name"]
                    return c
            return None

        def delete_collection(self, collection_id):
            before = len(store)
            store[:] = [c for c in store if c["id"] != collection_id]
            return len(store) < before

        def refresh_collection(self, collection_id):
            for c in store:
                if c["id"] == collection_id:
                    c["refreshed_at"] = "2026-10-16 12:00:00"
                    return c
            return None

    return FakeModule()


# 预定义测试数据（只读，不会修改）
_SampleCollections = [
    {"id": 1, "name": "我的歌单", "url": "https://music.163.com/playlist?id=1",
     "platform": "netease", "auto_name": 1,
     "created_at": "2026-10-15 10:00:00", "refreshed_at": "2026-10-15 12:00:00"},
    {"id": 2, "name": "夏日循环", "url": "https://music.163.com/playlist?id=2",
     "platform": "qqmusic", "auto_name": 0,
     "created_at": "2026-10-14 08:00:00", "refreshed_at": "2026-10-14 10:00:00"},
]


# ============================ list ============================

@pytest.mark.asyncio
async def test_list_returns_all(monkeypatch):
    monkeypatch.setattr("server._list_collections",
                        _make_fake(_SampleCollections).list_collections)
    result = await api_collections_list()
    assert len(result) == 2
    assert result[0]["name"] == "我的歌单"
    assert result[1]["name"] == "夏日循环"


@pytest.mark.asyncio
async def test_list_empty_returns_empty(monkeypatch):
    monkeypatch.setattr("server._list_collections",
                        _make_fake([]).list_collections)
    result = await api_collections_list()
    assert result == []


# ============================ create ============================

@pytest.mark.asyncio
async def test_create_success(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._create_collection", fh.create_collection)
    req = CreateCollectionRequest(url="https://music.163.com/playlist?id=99")
    result = await api_collections_create(req)
    assert result["id"] == 3
    assert result["name"] == "新收藏"


@pytest.mark.asyncio
async def test_create_with_name(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._create_collection", fh.create_collection)
    req = CreateCollectionRequest(url="https://music.163.com/playlist?id=99",
                                  name="睡前歌单")
    result = await api_collections_create(req)
    assert result["name"] == "睡前歌单"


@pytest.mark.asyncio
async def test_create_duplicate_raises_400(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._create_collection", fh.create_collection)
    req = CreateCollectionRequest(url="https://music.163.com/playlist?id=1")
    with pytest.raises(HTTPException) as exc:
        await api_collections_create(req)
    assert exc.value.status_code == 400
    assert "已收藏" in exc.value.detail


@pytest.mark.asyncio
async def test_create_parse_failure_raises_400(monkeypatch):
    def bad_create(url, name=""):
        raise ValueError("歌单解析失败: 模拟错误")
    monkeypatch.setattr("server._create_collection", bad_create)
    req = CreateCollectionRequest(url="https://bad.url/x")
    with pytest.raises(HTTPException) as exc:
        await api_collections_create(req)
    assert exc.value.status_code == 400
    assert "歌单解析失败" in exc.value.detail


# ============================ get ============================

@pytest.mark.asyncio
async def test_get_existing(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._get_collection", fh.get_collection)
    result = await api_collections_get(collection_id=1)
    assert result["id"] == 1
    assert result["name"] == "我的歌单"


@pytest.mark.asyncio
async def test_get_not_found_raises_404(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._get_collection", fh.get_collection)
    with pytest.raises(HTTPException) as exc:
        await api_collections_get(collection_id=999)
    assert exc.value.status_code == 404
    assert "收藏歌单不存在" in exc.value.detail


# ============================ update ============================

@pytest.mark.asyncio
async def test_update_name(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._update_collection", fh.update_collection)
    req = UpdateCollectionRequest(name="新名字")
    result = await api_collections_update(collection_id=1, req=req)
    assert result["name"] == "新名字"


@pytest.mark.asyncio
async def test_update_not_found_raises_404(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._update_collection", fh.update_collection)
    req = UpdateCollectionRequest(name="谁")
    with pytest.raises(HTTPException) as exc:
        await api_collections_update(collection_id=999, req=req)
    assert exc.value.status_code == 404


# ============================ delete ============================

@pytest.mark.asyncio
async def test_delete_existing(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._delete_collection", fh.delete_collection)
    result = await api_collections_delete(collection_id=1)
    assert result == {"status": "deleted"}


@pytest.mark.asyncio
async def test_delete_not_found_raises_404(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._delete_collection", fh.delete_collection)
    with pytest.raises(HTTPException) as exc:
        await api_collections_delete(collection_id=999)
    assert exc.value.status_code == 404
    assert "收藏歌单不存在" in exc.value.detail


# ============================ refresh ============================

@pytest.mark.asyncio
async def test_refresh_success(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._refresh_collection", fh.refresh_collection)
    result = await api_collections_refresh(collection_id=1)
    assert result["status"] == "ok"
    assert "刷新成功" in result["message"]
    assert result["collection"]["id"] == 1


@pytest.mark.asyncio
async def test_refresh_not_found_raises_404(monkeypatch):
    fh = _make_fake(_SampleCollections)
    monkeypatch.setattr("server._refresh_collection", fh.refresh_collection)
    with pytest.raises(HTTPException) as exc:
        await api_collections_refresh(collection_id=999)
    assert exc.value.status_code == 404
    assert "收藏歌单不存在" in exc.value.detail


@pytest.mark.asyncio
async def test_refresh_parse_failure_raises_400(monkeypatch):
    def bad_refresh(cid):
        raise ValueError("刷新失败: 网络超时")
    monkeypatch.setattr("server._refresh_collection", bad_refresh)
    with pytest.raises(HTTPException) as exc:
        await api_collections_refresh(collection_id=1)
    assert exc.value.status_code == 400
    assert "刷新失败" in exc.value.detail


# ============================ 路由不冲突 ============================

def test_collections_routes_not_shadowed():
    """静态子路由 /api/collections 和参数路由 /api/collections/{id} 不应互相干扰。"""
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

    # GET /api/collections 应命中列表路由，而非参数路由
    assert first_match("GET", "/api/collections") == "/api/collections"
    assert first_match("POST", "/api/collections") == "/api/collections"
    # 带数字 ID 的详情路由
    assert first_match("GET", "/api/collections/42") == "/api/collections/{collection_id}"
    assert first_match("DELETE", "/api/collections/42") == "/api/collections/{collection_id}"
    assert first_match("PUT", "/api/collections/42") == "/api/collections/{collection_id}"
    # refresh 子路由
    assert first_match("POST", "/api/collections/42/refresh") == \
        "/api/collections/{collection_id}/refresh"
