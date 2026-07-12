from fastapi import APIRouter, HTTPException
from app.schemas.download import SearchRequest, SearchResponse
from app.services.parser_factory import get_parser, all_parsers

router = APIRouter()


@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest):
    if req.platform == "all":
        parsers = all_parsers()
    else:
        parser = get_parser(req.platform)
        if not parser:
            raise HTTPException(400, f"不支持的平台: {req.platform}")
        parsers = [parser]

    all_results = []
    for parser in parsers:
        try:
            results = await parser.search(req.keyword)
            all_results.extend(results)
        except Exception:
            continue

    return SearchResponse(results=all_results)
