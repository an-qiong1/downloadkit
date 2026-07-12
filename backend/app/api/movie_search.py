"""
全网影视搜索 API
聚合 YouTube + Bilibili + BT 磁力搜索结果
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.parser_factory import get_parser
from app.services.torrent_search import search_torrents, TorrentResult

router = APIRouter()


class MovieSearchRequest(BaseModel):
    keyword: str
    sources: str = "all"  # all / youtube / bilibili / bt / youtube+bilibili


class MediaSearchItem(BaseModel):
    title: str
    source: str  # youtube / bilibili / bt
    url: str = ""
    magnet: str = ""
    duration: int = 0
    thumbnail: str = ""
    size: str = ""
    seeders: int = 0


class MovieSearchResponse(BaseModel):
    results: list[MediaSearchItem]
    total: int


@router.post("/movie", response_model=MovieSearchResponse)
async def search_movie(req: MovieSearchRequest):
    """全网影视搜索 - 同时搜索 YouTube + Bilibili + BT"""
    keyword = req.keyword.strip()
    if not keyword:
        raise HTTPException(400, "请输入搜索关键词")

    search_all = req.sources == "all"
    sources = req.sources.split("+") if not search_all else ["youtube", "bilibili", "bt"]

    all_results: list[MediaSearchItem] = []

    # 1. YouTube 搜索
    if "all" in sources or "youtube" in sources:
        try:
            yt_parser = get_parser("youtube")
            if yt_parser:
                yt_results = await yt_parser.search(keyword)
                for r in yt_results:
                    all_results.append(MediaSearchItem(
                        title=r.title,
                        source="youtube",
                        url=r.url,
                        duration=r.duration,
                        thumbnail=r.thumbnail,
                    ))
        except Exception as e:
            print(f"YouTube 搜索失败: {e}")

    # 2. Bilibili 搜索
    if "all" in sources or "bilibili" in sources:
        try:
            bl_parser = get_parser("bilibili")
            if bl_parser:
                bl_results = await bl_parser.search(keyword)
                for r in bl_results:
                    all_results.append(MediaSearchItem(
                        title=r.title,
                        source="bilibili",
                        url=r.url,
                        duration=r.duration,
                        thumbnail=r.thumbnail,
                    ))
        except Exception as e:
            print(f"Bilibili 搜索失败: {e}")

    # 3. BT 磁力搜索
    if "all" in sources or "bt" in sources:
        try:
            bt_results = await search_torrents(keyword)
            for r in bt_results:
                all_results.append(MediaSearchItem(
                    title=r.title,
                    source="bt",
                    magnet=r.magnet,
                    size=r.size,
                    seeders=r.seeders,
                ))
        except Exception as e:
            print(f"BT 搜索失败: {e}")

    # 去重（按标题简单去重）
    seen_titles = set()
    unique_results = []
    for r in all_results:
        key = r.title[:50].lower().strip()
        if key not in seen_titles:
            seen_titles.add(key)
            unique_results.append(r)

    return MovieSearchResponse(
        results=unique_results[:50],  # 最多返回50条
        total=len(unique_results),
    )
