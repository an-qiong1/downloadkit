"""
抖音第三方解析API模块
支持：本地自部署 parse-video / 山海云端API / limmy / TenAPI / FurryAPI
"""

import re
import json
from typing import Optional, List

import httpx

from .douyin import DouyinContent, ContentType, MediaItem, MotionPhotoPair
from .logger import get_logger

logger = get_logger("douyin_third_party")


class ParseVideoLocalParser:
    """parse-video-py 风格 API - 本地自部署（推荐）"""

    API_URLS = [
        "http://localhost:8000/video/share/url/parse",  # 自部署
    ]

    async def parse(self, url: str) -> Optional[DouyinContent]:
        for api_url in self.API_URLS:
            try:
                logger.info(f"[ParseVideo] 尝试本地API: {api_url}")

                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(api_url, params={"url": url})
                    resp.raise_for_status()
                    data = resp.json()

                result = data.get("data", data)
                if not result:
                    continue

                content = DouyinContent(
                    item_id=self._extract_id(url),
                    title=result.get("title", ""),
                    author=result.get("author", {}).get("name", "") if isinstance(result.get("author"), dict) else str(result.get("author", "")),
                    cover=result.get("cover_url", ""),
                )

                images = result.get("images", [])
                has_live_photo = False

                for img in images:
                    if isinstance(img, dict):
                        img_url = img.get("url", "")
                        live_photo_url = img.get("live_photo_url", "")

                        if img_url:
                            content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))

                        if live_photo_url:
                            has_live_photo = True
                            pair_img = MediaItem(url=img_url, type="image", file_ext="jpg")
                            pair_vid = MediaItem(url=live_photo_url, type="video", file_ext="mp4")
                            content.motion_photo_pairs.append(MotionPhotoPair(image=pair_img, video=pair_vid))
                    elif isinstance(img, str):
                        content.images.append(MediaItem(url=img, type="image", file_ext="jpg"))

                if has_live_photo:
                    content.content_type = ContentType.ANIMATED
                    logger.info(f"[ParseVideo] ✅ 实况照片 {len(content.motion_photo_pairs)} 对")
                elif images:
                    content.content_type = ContentType.IMAGE
                    logger.info(f"[ParseVideo] ✅ 图文 {len(content.images)} 张")
                else:
                    video_url = result.get("video_url", "")
                    if video_url:
                        content.content_type = ContentType.VIDEO
                        content.video_url = video_url
                        logger.info(f"[ParseVideo] ✅ 视频")
                    else:
                        continue

                return content

            except Exception as e:
                logger.error(f"[ParseVideo] 失败: {e}")
                continue

        return None

    def _extract_id(self, url: str) -> str:
        patterns = [r'/(?:video|note|slides)/(\d+)', r'(\d{15,25})']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return "unknown"


class LimmyParser:
    """limmy.top API - 较稳定，支持实况照片"""

    API_URL = "https://api.limmy.top/video/douyin/"

    async def parse(self, url: str) -> Optional[DouyinContent]:
        try:
            logger.info(f"[Limmy] 尝试解析: {url}")

            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(self.API_URL, params={"url": url})
                resp.raise_for_status()
                data = resp.json()

            if data.get("code") not in (200, 0, 1):
                logger.warning(f"[Limmy] API返回错误: {data.get('msg', '')}")
                return None

            result = data.get("data", data)
            if not result:
                return None

            content = DouyinContent(
                item_id=self._extract_id(url),
                title=result.get("title", ""),
                author=result.get("author", ""),
                cover=result.get("cover", ""),
            )

            video_url = result.get("url", "") or result.get("video_url", "")
            images = result.get("images", [])

            if images and len(images) > 0:
                content.content_type = ContentType.IMAGE
                for img in images:
                    if isinstance(img, str):
                        content.images.append(MediaItem(url=img, type="image", file_ext="jpg"))
                    elif isinstance(img, dict):
                        img_url = img.get("url", "")
                        live_url = img.get("live_photo_url", "")
                        if img_url:
                            content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
                        if live_url:
                            content.content_type = ContentType.ANIMATED
                            pair_img = MediaItem(url=img_url, type="image", file_ext="jpg")
                            pair_vid = MediaItem(url=live_url, type="video", file_ext="mp4")
                            content.motion_photo_pairs.append(MotionPhotoPair(image=pair_img, video=pair_vid))
            elif video_url:
                content.content_type = ContentType.VIDEO
                content.video_url = video_url
                content.file_ext = "mp4"
            else:
                return None

            logger.info(f"[Limmy] ✅ 解析成功: {content.content_type.value}")
            return content

        except Exception as e:
            logger.error(f"[Limmy] 解析失败: {e}")
            return None

    def _extract_id(self, url: str) -> str:
        patterns = [r'/(?:video|note|slides)/(\d+)', r'(\d{15,25})']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return "unknown"


class ShanHaiParser:
    """山海云端API解析器（备选）- 近期限制较多"""

    API_URL = "https://api.yyy001.com/api/videoparse"

    async def parse(self, url: str) -> Optional[DouyinContent]:
        try:
            logger.info(f"[ShanHai] 尝试API解析: {url}")

            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(self.API_URL, params={"url": url})
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "json" not in content_type:
                    logger.warning(f"[ShanHai] 响应不是JSON: {content_type}")
                    return None

                data = resp.json()

            if data.get("code") != 200:
                logger.warning(f"[ShanHai] API返回错误: {data.get('msg', '未知错误')}")
                return None

            result = data.get("data", {})
            if not result:
                return None

            content = DouyinContent(
                item_id=self._extract_id(url),
                title=result.get("title", ""),
                author=result.get("author", ""),
                cover=result.get("cover", ""),
            )

            video_url = result.get("url", "")
            images = result.get("images", [])

            if images and len(images) > 0:
                content.content_type = ContentType.IMAGE
                for img_url in images:
                    if isinstance(img_url, str):
                        content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
                    elif isinstance(img_url, dict):
                        img_url_str = img_url.get("url", "")
                        live_photo_url = img_url.get("live_photo_url", "")

                        if img_url_str:
                            content.images.append(MediaItem(url=img_url_str, type="image", file_ext="jpg"))

                        if live_photo_url:
                            content.content_type = ContentType.ANIMATED
                            pair_img = MediaItem(url=img_url_str, type="image", file_ext="jpg")
                            pair_vid = MediaItem(url=live_photo_url, type="video", file_ext="mp4")
                            content.motion_photo_pairs.append(MotionPhotoPair(image=pair_img, video=pair_vid))
            elif video_url:
                content.content_type = ContentType.VIDEO
                content.video_url = video_url
                content.file_ext = "mp4"
            else:
                return None

            return content

        except Exception as e:
            logger.error(f"[ShanHai] 解析失败: {e}")
            return None

    def _extract_id(self, url: str) -> str:
        patterns = [r'/(?:video|note|slides)/(\d+)', r'(\d{15,25})']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return "unknown"


class TenAPIParser:
    """TenAPI解析器 - 稳定但数据较简单"""

    API_URL = "https://tenapi.cn/v2/video"

    async def parse(self, url: str) -> Optional[DouyinContent]:
        try:
            logger.info(f"[TenAPI] 尝试解析: {url}")

            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.post(self.API_URL, data={"url": url})
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "json" not in content_type:
                    logger.warning(f"[TenAPI] 响应不是JSON: {content_type}")
                    return None

                data = resp.json()

            if data.get("code") != 200:
                logger.warning(f"[TenAPI] API返回错误: {data.get('msg', '未知错误')}")
                return None

            result = data.get("data", {})
            if not result:
                return None

            content = DouyinContent(
                item_id=self._extract_id(url),
                title=result.get("title", ""),
                author=result.get("author", ""),
                cover=result.get("cover", ""),
            )

            video_url = result.get("url", "")
            images = result.get("images", [])

            if images and len(images) > 0:
                content.content_type = ContentType.IMAGE
                for img_url in images:
                    if isinstance(img_url, str):
                        content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
            elif video_url:
                content.content_type = ContentType.VIDEO
                content.video_url = video_url
                content.file_ext = "mp4"
            else:
                return None

            logger.info(f"[TenAPI] ✅ 解析成功: {content.content_type.value}")
            return content

        except Exception as e:
            logger.error(f"[TenAPI] 解析失败: {e}")
            return None

    def _extract_id(self, url: str) -> str:
        patterns = [r'/(?:video|note|slides)/(\d+)', r'(\d{15,25})']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return "unknown"


class FurryParser:
    """FurryAPI 解析器 - 免费公开 API，支持视频/图文/统计数据"""

    API_URL = "https://api.furry.ist/douyin"

    async def parse(self, url: str) -> Optional[DouyinContent]:
        try:
            logger.info(f"[Furry] 尝试解析: {url}")

            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(self.API_URL, params={"url": url})
                resp.raise_for_status()
                data = resp.json()

            if not data.get("ok"):
                logger.warning(f"[Furry] API返回错误: {data.get('message', '')}")
                return None

            result = data.get("data", {})
            if not result:
                return None

            content = DouyinContent(
                item_id=result.get("aweme_id", self._extract_id(url)),
                title=result.get("desc", ""),
                author=result.get("nickname", "") or (result.get("author", {}) or {}).get("nickname", ""),
                cover=result.get("cover", ""),
            )

            # 判断类型
            content_type = result.get("type", "video")
            video_url = result.get("video_url", "")
            image_list = result.get("image_url_list", [])

            if content_type == "image" and image_list:
                content.content_type = ContentType.IMAGE
                for img_url in image_list:
                    if isinstance(img_url, str):
                        content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
            elif video_url:
                content.content_type = ContentType.VIDEO
                content.video_url = video_url
                content.file_ext = "mp4"
            elif image_list:
                content.content_type = ContentType.IMAGE
                for img_url in image_list:
                    if isinstance(img_url, str):
                        content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
            else:
                return None

            logger.info(f"[Furry] ✅ 解析成功: {content.content_type.value}")
            return content

        except Exception as e:
            logger.error(f"[Furry] 解析失败: {e}")
            return None

    def _extract_id(self, url: str) -> str:
        patterns = [r'/(?:video|note|slides)/(\d+)', r'(\d{15,25})']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return "unknown"


class DouyinTikTokScraperParser:
    """douyin-tiktok-scraper pip包解析器（可选依赖）
    
    安装：pip install douyin-tiktok-scraper
    参考：https://github.com/Evil0ctal/Douyin_Tiktok_Scraper_PyPi
    使用 Evil0ctal 的 hybrid_parsing 方法，支持抖音/TikTok/B站
    """

    name = "douyin_tiktok_scraper"
    _available = False
    
    @classmethod
    def check_available(cls) -> bool:
        if cls._available:
            return True
            try:
                import douyin_tiktok_scraper
                cls._available = True
                logger.info("[ScraperPkg] douyin-tiktok-scraper 可用")
                return True
            except ImportError:
                logger.info("[ScraperPkg] douyin-tiktok-scraper 未安装")
                return False

    async def parse(self, url: str) -> Optional[DouyinContent]:
        if not self.check_available():
            return None
        
        try:
            logger.info(f"[ScraperPkg] 尝试 hybrid_parsing: {url}")
            from douyin_tiktok_scraper.scraper import Scraper
            api = Scraper()
            result = await api.hybrid_parsing(url)
            
            if result.get("status") != "success":
                logger.error(f"[ScraperPkg] 解析失败: {result.get('message', '')}")
                return None
            
            data = result.get("data", {})
            if not data:
                return None
            
            content = DouyinContent(
                item_id=data.get("aweme_id", "") or data.get("video_id", ""),
                title=data.get("desc", ""),
                author=data.get("author", {}).get("nickname", "") if isinstance(data.get("author"), dict) else str(data.get("author", "")),
                cover=data.get("cover", ""),
            )
            
            # 提取无水印视频URL
            video_data = data.get("video", {}) or data.get("video_data", {})
            if isinstance(video_data, dict):
                # 优先无水印
                no_watermark = video_data.get("no_watermark") or video_data.get("no_watermark_url") or video_data.get("play_url")
                watermark = video_data.get("watermark") or video_data.get("watermark_url") or video_data.get("playwm_url")
                
                if no_watermark:
                    content.video_url = no_watermark
                    content.content_type = ContentType.VIDEO
                    content.file_ext = "mp4"
                elif watermark:
                    content.video_url = watermark
                    content.video_url_watermark = watermark
                    content.content_type = ContentType.VIDEO
            
            # 提取图片（图文/实况）
            image_data = data.get("images", []) or data.get("image_data", [])
            if image_data:
                has_live = False
                for img in image_data:
                    if isinstance(img, dict):
                        img_url = img.get("url", "") or img.get("download_url", "")
                        live_url = img.get("live_photo", {}).get("url", "") if isinstance(img.get("live_photo"), dict) else ""
                        
                        if img_url:
                            content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
                        
                        if live_url:
                            has_live = True
                            content.motion_photo_pairs.append(MotionPhotoPair(
                                image=MediaItem(url=img_url, type="image", file_ext="jpg"),
                                video=MediaItem(url=live_url, type="video", file_ext="mp4"),
                            ))
                    elif isinstance(img, str):
                        content.images.append(MediaItem(url=img, type="image", file_ext="jpg"))
                
                if has_live:
                    content.content_type = ContentType.ANIMATED
                elif not content.video_url:
                    content.content_type = ContentType.IMAGE
            
            if not content.video_url and not content.images:
                return None
            
            logger.info(f"[ScraperPkg] ✅ 解析成功: {content.content_type.value}")
            return content
            
        except Exception as e:
            logger.error(f"[ScraperPkg] 解析失败: {e}")
            return None


# 解析器实例
_local_parser = ParseVideoLocalParser()
_limmy_parser = LimmyParser()
_shanhai_parser = ShanHaiParser()
_tenapi_parser = TenAPIParser()
_furry_parser = FurryParser()
_scraper_parser = DouyinTikTokScraperParser()


async def parse_with_third_party(url: str) -> Optional[DouyinContent]:
    """
    尝试第三方解析，失败返回None

    优先级：
    0. douyin-tiktok-scraper（可选pip包，Evil0ctal官方维护，安装后可用）
    1. 本地 parse-video-py 自部署（最快、最可靠）
    2. FurryAPI（新加入，稳定免费公开API，支持视频/图文/统计数据）
    3. limmy.top API（稳定公共源）
    4. TenAPI（稳定但数据简单）
    5. 山海云端 API（备选，近期限制较多）
    """
    parsers = [
        ("douyin-tiktok-scraper", _scraper_parser),
        ("本地parse-video", _local_parser),
        ("FurryAPI", _furry_parser),
        ("Limmy", _limmy_parser),
        ("TenAPI", _tenapi_parser),
        ("山海云端", _shanhai_parser),
    ]

    for name, parser in parsers:
        try:
            content = await parser.parse(url)
            if content:
                return content
        except Exception as e:
            logger.error(f"[ThirdParty] {name} 异常: {e}")

    logger.error("[ThirdParty] 所有第三方解析器均失败")
    return None
