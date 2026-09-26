from fastapi import APIRouter
from app.api.downloads import router as downloads_router
from app.api.search import router as search_router
from app.api.playlists import router as playlists_router
from app.api.media import router as media_router
from app.api.collections import router as collections_router
from app.api.ws import router as ws_router

api_router = APIRouter()
api_router.include_router(downloads_router, prefix="/downloads", tags=["Downloads"])
api_router.include_router(search_router, prefix="/search", tags=["Search"])
api_router.include_router(playlists_router, prefix="/playlists", tags=["Playlists"])
api_router.include_router(collections_router, prefix="/collections", tags=["Collections"])
api_router.include_router(media_router, prefix="/media", tags=["Media"])
api_router.include_router(ws_router, tags=["WebSocket"])
