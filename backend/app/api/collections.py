"""歌单收藏 API 路由"""

from fastapi import APIRouter, HTTPException
from app.schemas.collection import (
    CollectionItem,
    CollectionDetail,
    CreateCollectionRequest,
    UpdateCollectionRequest,
    RefreshResponse,
)
from downloadkit.collection import (
    list_collections as _list,
    get_collection as _get,
    create_collection as _create,
    update_collection as _update,
    delete_collection as _delete,
    refresh_collection as _refresh,
)

router = APIRouter()


@router.get("", response_model=list[CollectionItem])
async def api_list_collections():
    """获取所有收藏歌单列表"""
    return _list()


@router.post("", response_model=CollectionDetail)
async def api_create_collection(req: CreateCollectionRequest):
    """添加收藏歌单（解析后自动缓存歌曲列表）"""
    try:
        return _create(url=req.url, name=req.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{collection_id}", response_model=CollectionDetail)
async def api_get_collection(collection_id: int):
    """获取收藏歌单详情（含缓存曲目）"""
    result = _get(collection_id)
    if not result:
        raise HTTPException(404, "收藏歌单不存在")
    return result


@router.put("/{collection_id}", response_model=CollectionDetail)
async def api_update_collection(collection_id: int, req: UpdateCollectionRequest):
    """更新收藏歌单信息（重命名等）"""
    kwargs = {}
    if req.name is not None:
        kwargs["name"] = req.name

    result = _update(collection_id, **kwargs)
    if not result:
        raise HTTPException(404, "收藏歌单不存在")
    return result


@router.delete("/{collection_id}")
async def api_delete_collection(collection_id: int):
    """删除收藏歌单（级联删除缓存曲目）"""
    ok = _delete(collection_id)
    if not ok:
        raise HTTPException(404, "收藏歌单不存在")
    return {"status": "deleted"}


@router.post("/{collection_id}/refresh", response_model=RefreshResponse)
async def api_refresh_collection(collection_id: int):
    """刷新收藏歌单（重新解析链接，更新缓存曲目列表）"""
    try:
        result = _refresh(collection_id)
        if not result:
            raise HTTPException(404, "收藏歌单不存在")
        song_count = len(result.get("tracks", []))
        return RefreshResponse(
            collection=result,
            status="ok",
            message=f"刷新成功，共 {song_count} 首歌曲",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
