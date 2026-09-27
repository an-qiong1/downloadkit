"""
抖音/TikTok 无水印解析下载模块
优化版 - 支持官方解析 + 第三方API + 实况照片合并

关键参考：
- https://github.com/HuanNan520/dyfetch
- https://github.com/xiaofeiwuuu/watermark-remover-server
"""

import re
import json
import asyncio
import time
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Any

import httpx
import execjs
from .logger import get_logger

logger = get_logger("douyin")

from .utils import download_file, sanitize_filename, get_download_subdir


class ContentType(Enum):
    VIDEO = "video"
    IMAGE = "image"
    ANIMATED = "animated"  # 实况照片/动态照片


@dataclass
class MediaItem:
    url: str
    type: str = "image"  # "image" 或 "video"
    file_ext: str = "jpg"


@dataclass
class MotionPhotoPair:
    """实况照片配对（一张图片对应一段短视频）"""
    image: MediaItem
    video: MediaItem


@dataclass
class DouyinContent:
    item_id: str
    content_type: ContentType = ContentType.VIDEO
    title: str = ""
    author: str = ""
    cover: str = ""
    description: str = ""

    video_url: str = ""
    video_url_watermark: str = ""
    video_quality: str = ""

    images: List[MediaItem] = field(default_factory=list)
    motion_photo_pairs: List[MotionPhotoPair] = field(default_factory=list)

    file_ext: str = "mp4"
    file_path: str = ""

    # 视频发布日期 YYYY-MM-DD（页面「发布时间」/ 详情 create_time）；
    # 取不到为空串 —— 文件命名层会回落 douyin_<作品ID>，不硬造日期
    publish_date: str = ""

    # ---- 浏览器后端新增字段（2026-09-26）----
    # backend: "browser" 或 "legacy"，标识解析路径
    backend: str = "legacy"
    # author_sec_uid: 作者稳定 ID，订阅功能用
    author_sec_uid: str = ""
    # stream_size: 视频实际总长（字节），来自 Content-Range
    stream_size: int = 0


def _fmt_publish_date(ts) -> str:
    """create_time（unix 秒/毫秒）→ YYYY-MM-DD；拿不到返回空串

    按 UTC+8 换算（抖音显示的发布时刻即北京时间），与页面「发布时间」
    抓到的日期保持一致，不随机器时区漂移。
    """
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    if ts > 10 ** 12:  # 毫秒时间戳
        ts //= 1000
    from datetime import datetime, timedelta, timezone
    try:
        return datetime.fromtimestamp(
            ts, tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def build_download_base(content: "DouyinContent") -> str:
    """下载文件名主干（不含扩展名）。

    用户拍板格式（2026-09-27）：`标题 2026-09-27.mp4` —— 标题在前、
    发布日期在后；拿不到发布日期就回落旧命名 `douyin_<作品ID>`，不硬造。
    长度封顶 120 字符：Windows 路径 260 上限，目录 + 日期 + 后缀要留余量。
    """
    base = sanitize_filename((content.title or "").strip())
    if not content.publish_date or base == "unknown":
        return f"douyin_{content.item_id}"
    if len(base) > 120:
        base = base[:120].rstrip()
    return f"{base} {content.publish_date}"


def _existing_target(candidates) -> Optional[Path]:
    """按候选名找已存在的文件（新命名在前，旧命名 douyin_<id> 兜底）

    旧文件不算「可下载」：同一作品曾以旧命名落盘的，切换新命名后
    重下不许再下出第二份（订阅增量判定走 aweme_id 水位线，与此无关）。
    """
    for p in candidates:
        if p is not None and p.exists():
            return p
    return None


class OptimizedOfficialParser:
    """优化版官方解析器 - 参考xiaofeiwuuu/watermark-remover-server"""
    
    name = "optimized_official"
    
    # 多个User-Agent，模拟不同设备
    USER_AGENTS = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    ]
    
    _abogus_gen = None  # 缓存 ABogusGenerator 实例（延迟初始化）
    _ttwid_cache = None  # 缓存 ttwid，避免每次解析重复 HTTP 请求
    _cookie_cache = None  # 缓存 cookie，避免重复文件 I/O 和浏览器访问
    
    def _get_abogus_generator(self):
        """获取缓存的 ABogusGenerator 实例（保持浏览器指纹一致）"""
        if self._abogus_gen is None:
            from .a_bogus import ABogusGenerator
            import random
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            self._abogus_gen = ABogusGenerator(user_agent=ua)
        return self._abogus_gen
    
    async def parse(self, url: str) -> Optional[DouyinContent]:
        try:
            logger.info(f"[Step 0] 开始解析链接: {url}")
            
            # 第一步：解析URL获取item_id和最终URL
            ua = self.USER_AGENTS[0]
            logger.info(f"[Step 1] 解析URL获取item_id")
            item_id, final_url = await self._resolve_url(url, ua)
            if not item_id:
                raise ValueError("[Step 1] 无法提取视频ID")
            
            logger.info(f"[Step 1] 视频ID: {item_id}, 最终URL: {final_url}")
            
            # 第二步：检测内容类型
            is_slides = (
                '/share/slides/' in final_url or
                'is_slides=1' in final_url or
                '/slides/' in final_url or
                '/note/' in final_url
            )
            logger.info(f"[Step 2] 内容类型: {'slides/图文' if is_slides else 'video'}")
            
            if is_slides:
                # Step 2a: slidesinfo API（无a_bogus优先）
                logger.info(f"[Step 2a] 通过slidesinfo API获取slides数据")
                content = await self._fetch_slides_via_api(item_id, ua)
                
                # API返回了视频或实况照片（有视频配对）→ 直接返回
                if content and (content.content_type == ContentType.VIDEO or content.motion_photo_pairs):
                    logger.info(f"[Step 2a] API返回实况照片/视频，直接使用")
                    return content
                
                # API返回了图片但没有视频 → 保留作为备选，继续尝试浏览器解析
                api_images = content if (content and content.images and content.content_type == ContentType.IMAGE) else None
                if api_images:
                    logger.info(f"[Step 2a] API返回 {len(api_images.images)} 张图片，继续尝试浏览器解析获取实况视频")

                # Step 2b: iesdouyin分享页
                logger.warning(f"[Step 2b] 尝试iesdouyin分享页")
                fallback_url = f"https://www.iesdouyin.com/share/video/{item_id}/"
                html = await self._fetch_page(fallback_url, ua)
                content = await self._parse_html(html, item_id)
                if content and content.motion_photo_pairs:
                    logger.info(f"[Step 2b] 分享页返回实况照片")
                    return content
                if content and content.content_type == ContentType.VIDEO:
                    # slides页面中og:video提取的视频通常是实况片段，不是完整视频
                    # 如果Step 2a已有图片数据，VIDEO类型不可信，继续尝试浏览器解析
                    if is_slides and api_images and api_images.images:
                        logger.info(f"[Step 2b] VIDEO来自og:video/fallback但已有图片数据，可能是实况片段，继续尝试浏览器解析")
                    else:
                        logger.info(f"[Step 2b] 分享页返回视频")
                        return content
                if content and content.images and content.content_type == ContentType.IMAGE:
                    logger.info(f"[Step 2b] 分享页返回图片但无实况视频，保存备选")
                    api_images = content

                # Step 2c: aweme/detail API
                logger.warning(f"[Step 2c] 尝试aweme/detail API")
                content = await self._fetch_via_aweme_detail_api(item_id, ua)
                if content and (content.content_type in (ContentType.VIDEO, ContentType.ANIMATED)):
                    return content
                if content and content.images and content.content_type == ContentType.IMAGE:
                    logger.info(f"[Step 2c] API返回图片但无实况视频，保存备选")
                    api_images = content

                # Step 2d: 浏览器解析（Playwright，最可能拿到实况视频）
                logger.info(f"[Step 2d] 尝试浏览器解析")
                content = await self._parse_via_browser(item_id)
                if content and (content.video_url or content.images):
                    return content

                # 所有路径都没有视频，用API的图片结果兜底
                if api_images:
                    logger.info(f"[Step 2] 所有实况视频路径失败，使用API图片结果兜底")
                    return api_images

            # 第三步：获取页面HTML并解析
            logger.info(f"[Step 3] 获取页面HTML并解析")
            html = await self._fetch_page(final_url, ua)
            content = await self._parse_html(html, item_id)

            if content and (content.video_url or content.images):
                return content

            # 第四步：HTML解析失败，尝试aweme/detail API兜底
            logger.warning(f"[Step 4] HTML解析失败，尝试aweme/detail API兜底")
            content = await self._fetch_via_aweme_detail_api(item_id, ua)
            if content and (content.video_url or content.images):
                return content

            logger.error("[Result] 所有解析方法均失败")
            return None
            
        except Exception as e:
            logger.error(f"[Result] 解析异常: {e}")
            return None
    
    async def _resolve_url(self, url: str, ua: str) -> tuple[Optional[str], str]:
        """解析链接，获取真实地址和视频ID
        
        优化策略：
        1. follow_redirects=True 由 httpx 自动跟踪完整重定向链
        2. 从最终 URL（resp.url）提取 item_id
        3. 如果最终 URL 没有，遍历全部中间跳转 URL
        4. 所有 URL 都提取不到时，尝试通过 /share/ 页面间接获取
        """
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        
        # 方案1：自动跟随重定向，让 httpx 处理完整链
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            final_url = str(resp.url)
            logger.info(f"[Resolve] 最终URL: {final_url}")
            
            # 从最终 URL 提取
            item_id = self._extract_id_from_url(final_url)
            if item_id:
                return item_id, final_url
            
            # 从重定向历史中提取（遍历所有中间 URL）
            history_urls = [str(r.url) for r in resp.history] + [final_url]
            for hist_url in history_urls:
                item_id = self._extract_id_from_url(hist_url)
                if item_id:
                    logger.info(f"[Resolve] 从历史URL提取到ID: {hist_url}")
                    return item_id, final_url
            
            # 如果上面的 URL 中还没有 ID，尝试从页面中提取
            logger.info(f"[Resolve] URL链中无显式ID，尝试从页面HTML提取")
            try:
                page_text = resp.text[:5000]  # 只取前5K字符
                # 搜索 JSON 中的 aweme_id
                id_in_json = re.search(r'"aweme_id"?\s*:\s*"(\d{15,25})"', page_text)
                if id_in_json:
                    item_id = id_in_json.group(1)
                    logger.info(f"[Resolve] 从HTML JSON提取到ID: {item_id}")
                    return item_id, final_url
                # 搜索 itemId
                id_in_js = re.search(r'itemId["\']?\s*[:=]\s*["\']?(\d{15,25})', page_text)
                if id_in_js:
                    item_id = id_in_js.group(1)
                    logger.info(f"[Resolve] 从HTML JS提取到ID: {item_id}")
                    return item_id, final_url
            except Exception:
                pass
        
        logger.info(f"[Resolve] 无法提取视频ID")
        return None, final_url
    
    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """从URL中提取ID - 增强版"""
        patterns = [
            r'/(?:video|note|slides)/(\d+)',
            r'/share/(?:user|video|slides)/(\d+)',
            r'modal_id=(\d+)',
            r'item_ids?=(\d+)',
            r'aweme_id[=/](\d+)',
            r'/(\d{17,21})/',           # 新的抖音ID长度格式
            r'(\d{15,25})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _gen_msToken(self) -> str:
        """生成 msToken 参数（虚假但格式正确）
        
        参考 Evil0ctal 项目的 gen_false_msToken 实现：
        生成随机 128 字符的 base64 风格字符串
        """
        import random
        import string
        # 生成 126 位随机字符 + "==" 后缀（共128位）
        chars = string.ascii_letters + string.digits + '-_'
        return ''.join(random.choices(chars, k=126)) + "=="

    _x_bogus_compiled = None

    @classmethod
    def _get_x_bogus_compiled(cls):
        """编译并缓存 X-Bogus.js（execjs 包装）
        
        使用 douyin-tiktok-scraper 包自带的 X-Bogus.js 文件，
        通过 Node.js (execjs) 执行签名生成。
        """
        if cls._x_bogus_compiled is not None:
            return cls._x_bogus_compiled
        try:
            import douyin_tiktok_scraper
            import os
            pkg_dir = os.path.dirname(douyin_tiktok_scraper.__file__)
            js_path = os.path.join(pkg_dir, 'X-Bogus.js')
            with open(js_path, 'r', encoding='utf-8') as f:
                js_content = f.read()
            cls._x_bogus_compiled = execjs.compile(js_content)
            logger.info("[Parser] X-Bogus JS引擎编译成功")
        except Exception as e:
            logger.info(f"[Parser] X-Bogus JS引擎编译失败: {e}")
            cls._x_bogus_compiled = False  # 缓存失败状态
        return cls._x_bogus_compiled if cls._x_bogus_compiled else None

    def _generate_x_bogus(self, url: str, ua: str) -> str:
        """为 API URL 追加 X-Bogus 签名
        
        X-Bogus 由查询字符串 + User-Agent 通过 JS 算法生成，
        是抖音 Web API 绕过风控的关键签名（不同于 a_bogus）。
        """
        compiled = self._get_x_bogus_compiled()
        if not compiled:
            return url
        try:
            from urllib.parse import urlparse
            query = urlparse(url).query
            if not query:
                return url
            xbogus = compiled.call('sign', query, ua)
            signed_url = url + "&X-Bogus=" + xbogus
            logger.info(f"[Parser] X-Bogus 签名已追加")
            return signed_url
        except Exception as e:
            logger.info(f"[Parser] X-Bogus 生成失败: {e}")
            return url

    async def _get_ttwid(self, ua: str) -> Optional[str]:
        """获取ttwid cookie，用于抖音API鉴权
        
        通过 bytedance 的 ttwid 注册接口获取，参考 yt-dlp 和 Evil0ctal 项目的实现
        
        缓存策略：类变量 _ttwid_cache，session 内只请求一次
        """
        # 优先返回缓存
        if self._ttwid_cache is not None:
            logger.info(f"[Parser] 使用缓存的ttwid: {self._ttwid_cache[:30]}...")
            return self._ttwid_cache
        
        # 多组注册参数，提高成功率
        configs = [
            {"aid": 1768, "service": "www.ixigua.com", "region": "cn", "union": True},
            {"aid": 6383, "service": "www.douyin.com", "region": "cn", "union": True},
            {"aid": 1768, "service": "www.douyin.com", "region": "cn", "union": False},
        ]
        
        for cfg in configs:
            try:
                url = "https://ttwid.bytedance.com/ttwid/union/register/"
                data = {
                    "region": cfg["region"],
                    "aid": cfg["aid"],
                    "needFid": False,
                    "service": cfg["service"],
                    "migrate_info": {"ticket": "", "source": "node"},
                    "cbUrlProtocol": "https",
                    "union": cfg["union"],
                }
                headers = {
                    "User-Agent": ua,
                    "Content-Type": "application/json",
                }
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(url, json=data, headers=headers)
                    ttwid = resp.cookies.get("ttwid")
                    if ttwid:
                        logger.info(f"[Parser] 获取ttwid成功 (aid={cfg['aid']}): {ttwid[:30]}...")
                        self._ttwid_cache = ttwid
                        return ttwid
                    else:
                        logger.info(f"[Parser] 获取ttwid失败 (aid={cfg['aid']}): {resp.text[:60]}")
            except Exception as e:
                logger.info(f"[Parser] 获取ttwid异常 (aid={cfg['aid']}): {e}")
                continue
        
        return None

    def _load_user_cookies(self) -> str:
        """加载用户提供的抖音 Cookie（多路径尝试）

        优先级：
        1. 用户在 UI 配置的 cookie.douyin_path（设置页填的文件路径）
        2. `~/.downloadkit/cookies/douyin.txt` — 纯文本 Cookie 字符串
        3. `~/.downloadkit/cookies/douyin.json` — JSON 格式 {name: value}
        4. 浏览器（Edge/Chrome）中 .douyin.com 域的 Cookie
        5. 兜底：仅返回已有 ttwid

        Returns:
            Cookie 字符串（可能为空）
        """
        # 类变量缓存，避免重复文件 I/O 和浏览器访问
        if self._cookie_cache is not None:
            return self._cookie_cache
        from pathlib import Path
        from .utils import read_cookie_from_file, get_config_value

        # 1. 优先：用户在 UI 配置的 cookie.douyin_path
        user_path = (get_config_value("cookie", "douyin_path", "") or "").strip()
        if user_path:
            cookie = read_cookie_from_file(user_path)
            if cookie:
                logger.info(f"[Cookie] 从 UI 配置路径加载抖音 Cookie: {user_path}")
                self._cookie_cache = cookie
                return cookie

        # 2. 默认目录下的 douyin.txt / douyin.json
        cookie_dirs = [
            Path.home() / '.downloadkit' / 'cookies',
        ]
        for d in cookie_dirs:
            for filename in ('douyin.txt', 'douyin.json'):
                f = d / filename
                if f.exists():
                    cookie = read_cookie_from_file(str(f))
                    if cookie:
                        logger.info(f"[Cookie] 从默认文件加载抖音 Cookie: {f}")
                        self._cookie_cache = cookie
                        return cookie

        # 3. 浏览器 Cookie
        try:
            from .browser_cookie import get_douyin_cookie_string
            for browser in ('edge', 'chrome'):
                try:
                    cookie_str = get_douyin_cookie_string(browser)
                    if cookie_str and 'sessionid' in cookie_str:
                        logger.info(f"[Cookie] 从 {browser} 浏览器加载抖音 Cookie (含sessionid)")
                        self._cookie_cache = cookie_str
                        return cookie_str
                except Exception:
                    continue
        except ImportError:
            pass

        logger.info(f"[Cookie] 未找到用户 Cookie，仅使用 ttwid")
        result = f"ttwid={self._ttwid_cache}" if self._ttwid_cache else ""
        self._cookie_cache = result
        return result

    async def _fetch_slides_via_api(self, item_id: str, ua: str) -> Optional[DouyinContent]:
        """通过API获取slides数据（多签名策略）
        
        签名策略（按优先级）：
        1. X-Bogus — 基于 JS 的 Web 端签名
        2. a_bogus — 基于 SM3 的纯 Python 签名（绕过 story_25_filter）
        3. 无签名 — 裸请求兜底
        """
        try:
            import random
            import string

            logger.info(f"[Parser] 通过slidesinfo API获取数据, ID: {item_id}")

            # 获取ttwid
            ttwid = await self._get_ttwid(ua)

            # 加载用户 Cookie
            user_cookie = self._load_user_cookies()
            base_cookie = f"ttwid={ttwid}" if ttwid else ""
            if user_cookie:
                if ttwid and 'ttwid' not in user_cookie:
                    base_cookie = f"ttwid={ttwid}; {user_cookie}"
                else:
                    base_cookie = user_cookie

            # 生成 web_id
            web_id = "75" + ''.join(random.choices(string.digits, k=15))

            # ---------- 构造请求配置 ----------
            def _build_configs(signer: str) -> list[dict]:
                configs = []
                # 方案1: iesdouyin slidesinfo（含完整参数）
                params_str = (
                    f"reflow_source=reflow_page"
                    f"&web_id={web_id}"
                    f"&device_id={web_id}"
                    f"&aweme_ids=%5B{item_id}%5D"
                    f"&request_source=200"
                )
                configs.append({
                    "url": f"https://www.iesdouyin.com/web/api/v2/aweme/slidesinfo/?{params_str}",
                    "ua": ua,
                    "label": f"iesdouyin slidesinfo ({signer})",
                })
                # 方案2: douyin.com 域名
                configs.append({
                    "url": f"https://www.douyin.com/aweme/v1/web/aweme/slidesinfo/?aweme_ids=%5B{item_id}%5D",
                    "ua": ua,
                    "label": f"douyin.com slidesinfo ({signer})",
                })
                return configs

            xbogus_configs = _build_configs("X-Bogus")
            a_bogus_configs = _build_configs("a_bogus")

            # 桌面版 Chrome UA（与签名兼容性更好）
            desktop_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

            # ========== 合并全部策略，并行请求 ==========
            all_entries = []
            # Phase 1: X-Bogus
            for cfg in xbogus_configs:
                all_entries.append((cfg, lambda url, ua: self._generate_x_bogus(url, ua)))
            # Phase 2: a_bogus
            for cfg in a_bogus_configs:
                all_entries.append((cfg, lambda url, ua, cookie=base_cookie: self._generate_a_bogus(url, ua, cookie)))
            # Phase 3: 裸请求
            for cfg in xbogus_configs:
                all_entries.append((cfg, None))

            def _check_slides_response(data):
                filter_list = data.get("filter_list", [])
                if filter_list:
                    reasons = [f.get("reason", "?") for f in filter_list]
                    logger.info(f"[Parser] slidesinfo API 内容被过滤, reasons={reasons}")
                    return None
                if data.get("status_code") != 0:
                    return None
                details = data.get("aweme_details", [])
                if details:
                    return self._parse_aweme_detail(details[0], item_id)
                return None

            result = await self._try_configs_parallel(all_entries, base_cookie, desktop_ua, _check_slides_response)
            if result:
                return result

            logger.info(f"[Parser] slidesinfo API 全部策略均失败")
            return None

        except Exception as e:
            logger.info(f"[Parser] slidesinfo API获取失败: {e}")
            return None

    def _build_detail_params(self, item_id: str) -> dict:
        """构建 aweme/detail 的完整浏览器指纹参数
        
        参考 Evil0ctal 项目的 BaseRequestModel，生成更完整的指纹参数
        """
        import random
        web_id = "73" + ''.join(random.choices('0123456789', k=17))
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "aweme_id": item_id,
            "pc_client_type": "1",
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "130.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "130.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "12",
            "device_memory": "8",
            "platform": "PC",
            "webid": web_id,
            "msToken": self._gen_msToken(),
        }

    async def _fetch_via_aweme_detail_api(self, item_id: str, ua: str) -> Optional[DouyinContent]:
        """通过aweme/detail API获取单个作品详情（多签名策略）
        
        签名策略（按优先级）：
        1. X-Bogus — 基于 JS (execjs) + X-Bogus.js 的 Web 端签名
        2. a_bogus — 基于 SM3 的纯 Python 签名（绕过 story_25_filter）
        3. 无签名 — 裸请求兜底
        
        参考 Evil0ctal 项目改进：
        1. 完整浏览器指纹参数
        2. msToken 参数（虚假但格式正确）
        3. 多组 API host + aid 组合
        4. 更完整的 Cookie 和请求头
        """
        try:
            logger.info(f"[Parser] 通过aweme/detail API获取数据, ID: {item_id}")

            # 获取 ttwid（尝试多组参数）
            ttwid = await self._get_ttwid(ua)
            if not ttwid:
                logger.info(f"[Parser] aweme/detail API: 无法获取ttwid")
                return None

            # 加载用户 Cookie（浏览器/配置文件）
            user_cookie = self._load_user_cookies()
            
            # 合并 Cookie
            base_cookie = f"ttwid={ttwid}"
            if user_cookie:
                base_cookie = user_cookie
                if 'ttwid' not in user_cookie:
                    base_cookie = f"ttwid={ttwid}; {user_cookie}"
                logger.info(f"[Parser] 已集成用户 Cookie (含sessionid: {'sessionid' in base_cookie})")

            # 构建基础参数（含msToken和完整浏览器指纹）
            base_params = self._build_detail_params(item_id)

            # 参数转URL查询字符串
            def build_url(host: str, params: dict) -> str:
                parts = [f"{k}={v}" for k, v in params.items()]
                return f"https://{host}/aweme/v1/web/aweme/detail/?{'&'.join(parts)}"

            # ----- 构造 X-Bogus 配置组 -----
            xbogus_configs = []
            for host in ("www.douyin.com", "www.iesdouyin.com"):
                xbogus_configs.append({
                    "url": build_url(host, base_params),
                    "ua": ua,
                    "label": f"{host} X-Bogus 完整参数",
                })
                for aid in ("6383", "1128"):
                    simple_params = {
                        "device_platform": "webapp",
                        "aid": aid,
                        "channel": "channel_pc_web",
                        "aweme_id": item_id,
                    }
                    xbogus_configs.append({
                        "url": build_url(host, simple_params),
                        "ua": ua,
                        "label": f"{host} X-Bogus aid={aid} 简单参数",
                    })

            # ----- 构造 a_bogus 配置组（用于绕过 story_25_filter） -----
            a_bogus_configs = []
            for host in ("www.douyin.com", "www.iesdouyin.com"):
                a_bogus_configs.append({
                    "url": build_url(host, base_params),
                    "ua": ua,
                    "label": f"{host} a_bogus 完整参数",
                })

            # 桌面版 Chrome UA（与签名兼容性更好）
            desktop_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
            # ========== 合并全部策略，并行请求 ==========
            all_entries = []
            # Phase 1: X-Bogus
            for cfg in xbogus_configs:
                all_entries.append((cfg, lambda url, ua: self._generate_x_bogus(url, ua)))
            # Phase 2: a_bogus
            for cfg in a_bogus_configs:
                all_entries.append((cfg, lambda url, ua, cookie=base_cookie: self._generate_a_bogus(url, ua, cookie)))
            # Phase 3: 裸请求
            for cfg in xbogus_configs:
                all_entries.append((cfg, None))

            def _check_detail_response(data):
                if data.get("status_code") == 8:
                    return None  # story_25_filter，交给其他配置尝试
                ad = data.get("aweme_detail")
                if ad:
                    return self._parse_aweme_detail(ad, item_id)
                return None

            result = await self._try_configs_parallel(all_entries, base_cookie, desktop_ua, _check_detail_response)
            if result:
                return result

            logger.info(f"[Parser] aweme/detail API 全部策略均失败")
            return None

        except Exception as e:
            logger.info(f"[Parser] aweme/detail API获取失败: {e}")
            return None

    def _generate_a_bogus(self, url: str, ua: str, cookie: str = "") -> str:
        """为 API URL 追加 a_bogus 签名
        
        a_bogus 是基于 SM3 哈希的移动端签名（不同于 X-Bogus），
        在绕过 story_25_filter 等内容限制方面效果更好。
        
        使用缓存的 ABogusGenerator 实例，保持浏览器指纹一致。
        """
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        params_str = parsed.query
        
        generator = self._get_abogus_generator()
        a_bogus = generator.generate(params_str, body="")
        
        separator = "&" if params_str else "?"
        return f"{url}{separator}a_bogus={a_bogus}"

    async def _try_configs_parallel(
        self,
        entries: list,
        base_cookie: str,
        desktop_ua: str,
        check_func,
    ) -> Optional[DouyinContent]:
        """并行执行一组带签名的 API 请求，返回首个通过 check_func 的结果
        
        Args:
            entries: [(config_dict, sign_fn_or_None), ...]
            base_cookie: Cookie 字符串
            desktop_ua: 桌面端 UA（用于 iOS UA 回退）
            check_func: callable(data_json) -> DouyinContent|None
        """
        import asyncio

        async def _execute_one(cfg, sign_fn):
            actual_ua = cfg["ua"] if "iPhone" not in cfg["ua"] else desktop_ua
            api_url = cfg["url"]
            if sign_fn:
                try:
                    api_url = sign_fn(api_url, actual_ua)
                except Exception as e:
                    logger.info(f"[Parser] 签名失败 ({cfg['label']}): {e}")
                    return None

            headers = {
                "User-Agent": actual_ua,
                "Referer": "https://www.douyin.com/",
                "Cookie": base_cookie,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                try:
                    resp = await client.get(api_url, headers=headers)
                    if resp.status_code != 200:
                        return None
                    return resp.json()
                except Exception as e:
                    logger.info(f"[Parser] 请求异常 ({cfg['label']}): {e}")
                    return None

        # 创建所有任务
        tasks = [asyncio.create_task(_execute_one(cfg, fn)) for cfg, fn in entries]
        logger.info(f"[Parser] 并行请求 {len(tasks)} 个配置...")

        while tasks:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                data = t.result()
                if data is None:
                    continue
                result = check_func(data)
                if result:
                    # 取消剩余 pending 任务
                    for p in pending:
                        p.cancel()
                    return result
            tasks = list(pending)

        return None

    async def _parse_via_browser(self, item_id: str) -> Optional[DouyinContent]:
        """
        使用Playwright浏览器解析页面，提取实况照片的视频URL
        
        优化策略：
        1. 多次循环切换所有slide，确保每个slide的视频都被加载
        2. 每次切换后立即收集页面上所有视频（全局收集）
        3. 最后按索引配对图片和视频
        """
        try:
            from playwright.async_api import async_playwright
            
            logger.info(f"[Browser] 使用Playwright浏览器解析...")
            
            content = DouyinContent(item_id=item_id)
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                
                url = f"https://www.douyin.com/note/{item_id}"
                logger.info(f"[Browser] 访问: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(8000)
                
                # 检测轮播项数量
                logger.info(f"[Browser] 通过Swiper API主动切换轮播项...")
                slide_count = await page.evaluate('''() => {
                    const swiperEl = document.querySelector('.swiper, [class*="swiper-container"]');
                    if (swiperEl && swiperEl.swiper) {
                        return swiperEl.swiper.slides.length;
                    }
                    return document.querySelectorAll('.dySwiperSlide:not(.swiper-slide-clone), .swiper-slide:not(.swiper-slide-clone)').length;
                }''')
                logger.info(f"[Browser] 检测到 {slide_count} 个轮播项")
                # 多次循环切换所有slide，确保每个slide的视频都被加载
                # 关键发现：抖音的实况照片视频不在slide容器内，需要在slide级别配对
                logger.info(f"[Browser] 开始多次循环切换轮播项...")
                
                # 存储每个slide的配对结果
                slide_pairs = {}
                all_img_urls = []  # 收集所有图片URL（即使无视频配对）
                seen_imgs = set()  # 去重
                
                for round_num in range(3):  # 优化：从5轮减到3轮
                    for i in range(slide_count):
                        # 跳过已配对的幻灯片
                        if i in slide_pairs:
                            continue
                        # 使用 Swiper API 切换
                        await page.evaluate('''(idx) => {
                            const swiperEl = document.querySelector('.swiper, [class*="swiper-container"]');
                            if (swiperEl && swiperEl.swiper) {
                                swiperEl.swiper.slideTo(idx);
                            }
                        }''', i)
                        await page.wait_for_timeout(800)
                        
                        # 点击触发视频加载
                        try:
                            await page.evaluate('''(idx) => {
                                const slides = document.querySelectorAll('.dySwiperSlide:not(.swiper-slide-clone), .swiper-slide:not(.swiper-slide-clone)');
                                if (idx < slides.length) {
                                    const img = slides[idx].querySelector('img');
                                    if (img) img.click();
                                }
                            }''', i)
                            await page.wait_for_timeout(800)
                        except Exception:
                            pass
                        
                        # 如果这个slide还没有配对成功，尝试收集
                        if i not in slide_pairs:
                            # 收集当前slide的图片和视频
                            slide_data = await page.evaluate('''(idx) => {
                                const slides = document.querySelectorAll('.dySwiperSlide:not(.swiper-slide-clone), .swiper-slide:not(.swiper-slide-clone)');
                                if (idx >= slides.length) return null;
                                
                                const slide = slides[idx];
                                
                                // 获取slide内的图片（取最大的一张）
                                const slideImgs = slide.querySelectorAll('img');
                                let bestImg = null;
                                let bestImgSize = 0;
                                for (const img of slideImgs) {
                                    const src = img.src || img.getAttribute('data-src') || '';
                                    const width = img.naturalWidth || img.width || 0;
                                    const height = img.naturalHeight || img.height || 0;
                                    const size = width * height;
                                    if (src && !src.startsWith('data:') && src.includes('douyinpic') 
                                        && size > bestImgSize && width >= 100 && height >= 100) {
                                        bestImg = src;
                                        bestImgSize = size;
                                    }
                                }
                                
                                // 获取slide内的视频
                                let bestVideo = null;
                                const videoEls = slide.querySelectorAll('video');
                                for (const v of videoEls) {
                                    const source = v.querySelector('source');
                                    const src = source ? source.src : (v.src || v.currentSrc || '');
                                    if (src && !src.includes('.mp3') && !src.includes('about:blank')) {
                                        bestVideo = src;
                                        break;
                                    }
                                }
                                
                                return { img: bestImg, vid: bestVideo };
                            }''', i)
                            
                            if slide_data and slide_data['img'] and slide_data['vid']:
                                slide_pairs[i] = slide_data
                                logger.info(f"[Browser] Slide {i}: 配对成功")
                            # 即使无视频也收集图片URL（用于兜底）
                            if slide_data and slide_data['img'] and slide_data['img'] not in seen_imgs:
                                seen_imgs.add(slide_data['img'])
                                all_img_urls.append(slide_data['img'])
                    
                    # 检查是否所有slide都配对成功
                    if len(slide_pairs) >= slide_count:
                        logger.info(f"[Browser] 第{round_num+1}轮完成，所有slide已配对")
                        break
                
                # 转换为pairs列表（按slide顺序）
                pairs = []
                for i in range(slide_count):
                    if i in slide_pairs:
                        pairs.append(slide_pairs[i])
                
                result = {
                    'pairs': pairs,
                    'pairCount': len(pairs),
                    'totalImages': len(pairs),
                    'totalVideos': len(pairs),
                    'slideCount': slide_count,
                    'imageUrls': [p['img'] for p in pairs],
                    'videoUrls': [p['vid'] for p in pairs],
                }

                
                await browser.close()
                
                # 处理结果
                logger.info(f"[Browser] 找到 {len(pairs)} 对实况照片")
                
                if pairs:
                    seen_videos = set()
                    for i, pair in enumerate(pairs):
                        img_url = pair['img']
                        vid_url = pair['vid']
                        
                        # 去重
                        if vid_url in seen_videos:
                            continue
                        seen_videos.add(vid_url)
                        
                        content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
                        pair_img = MediaItem(url=img_url, type="image", file_ext="jpg")
                        pair_vid = MediaItem(url=vid_url, type="video", file_ext="mp4")
                        content.motion_photo_pairs.append(MotionPhotoPair(image=pair_img, video=pair_vid))
                        logger.info(f"[Browser] 配对 {i+1}: img={img_url[:50]}... vid={vid_url[:50]}...")
                    
                    content.content_type = ContentType.ANIMATED
                else:
                    # 没有配对，但有图片则收集图片（用 all_img_urls 替代 pairs，因为 pairs 为空时啥也收不到）
                    for img_url in (all_img_urls[:20] if all_img_urls else []):
                        content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
                    if content.images:
                        logger.info(f"[Browser] 未找到实况照片配对，收集了 {len(content.images)} 张图片")
                        content.content_type = ContentType.IMAGE
                    else:
                        logger.info(f"[Browser] 未找到任何图片或视频")
                
                return content
                
        except ImportError:
            logger.info(f"[Browser] Playwright未安装，跳过浏览器解析")
            return None
        except Exception as e:
            logger.info(f"[Browser] 浏览器解析失败: {e}")
            return None
    
    async def _fetch_page(self, url: str, ua: str) -> str:
        """获取页面HTML"""
        headers = {
            "User-Agent": ua,
            "Referer": "https://www.douyin.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
    
    async def _parse_html(self, html: str, item_id: str) -> Optional[DouyinContent]:
        """解析HTML提取数据 - 支持多种数据格式
        
        尝试顺序：
        1. _ROUTER_DATA（旧版Douyin页面）
        2. __INITIAL_STATE__（新版Douyin页面）
        3. RENDER_DATA script 标签（SSR渲染数据）
        4. __PRELOADED_STATE__（预加载数据）
        5. 正则在HTML中暴力搜索
        6. fallback 提取器
        """
        # --- 方案1: _ROUTER_DATA（旧版） ---
        match = re.search(r'window\._ROUTER_DATA\s*=\s*', html)
        if not match:
            match = re.search(r'_ROUTER_DATA\s*=\s*', html)
        
        if match:
            logger.info(f"[Parser] 找到 _ROUTER_DATA")
            result = await self._parse_router_data(html, match, item_id)
            if result:
                return result
        
        # --- 方案2: __INITIAL_STATE__（新版） ---
        match = re.search(r'window\.__INITIAL_STATE__\s*=\s*', html)
        if match:
            logger.info(f"[Parser] 找到 __INITIAL_STATE__")
            start = match.end()
            data = self._extract_json(html, start)
            if data:
                result = self._parse_state_json(data, item_id)
                if result:
                    return result
        
        # --- 方案3: RENDER_DATA script 标签（SSR） ---
        render_match = re.search(
            r'<script[^>]*id=["\']RENDER_DATA["\'][^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if render_match:
            logger.info(f"[Parser] 找到 RENDER_DATA script")
            raw = render_match.group(1)
            # RENDER_DATA 内容是 HTML 实体编码的 JSON
            import html as html_mod
            decoded = html_mod.unescape(raw)
            data = self._extract_json(decoded, 0)
            if data:
                result = self._parse_state_json(data, item_id)
                if result:
                    return result
        
        # --- 方案4: __PRELOADED_STATE__ ---
        match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*', html)
        if match:
            logger.info(f"[Parser] 找到 __PRELOADED_STATE__")
            start = match.end()
            data = self._extract_json(html, start)
            if data:
                result = self._parse_state_json(data, item_id)
                if result:
                    return result
        
        # --- 方案5: 暴力搜索JSON中的aweme_detail ---
        logger.info(f"[Parser] 尝试暴力搜索HTML中的aweme_detail")
        # 搜索 {xxx, "aweme_detail": {...}} 模式
        ad_markers = [m.start() for m in re.finditer(r'"aweme_detail"\s*:', html)]
        for pos in ad_markers[:5]:  # 最多试5处
            data = self._extract_json(html, pos - 20 if pos > 20 else 0)
            if data:
                ad = None
                if isinstance(data, dict):
                    ad = data.get("aweme_detail")
                if ad:
                    result = self._parse_aweme_detail(ad, item_id)
                    if result:
                        logger.info(f"[Parser] 暴力搜索成功")
                        return result
        
        # 所有新方案失败，走fallback
        logger.info(f"[Parser] 所有JSON方案失败，走fallback")
        return await self._extract_from_html_fallback(html, item_id)
    
    async def _parse_router_data(self, html: str, match, item_id: str) -> Optional[DouyinContent]:
        """解析 _ROUTER_DATA 格式（从旧逻辑抽取）"""
        start = match.end()
        data = self._extract_json(html, start)
        
        if not data:
            return None
        
        loader_data = data.get("loaderData", data)
        logger.info(f"[Parser] loaderData keys: {list(loader_data.keys())[:10]}")
        
        # 查找数据字典 - 前缀匹配
        data_dict = {}
        for key in loader_data:
            if key.startswith('slides_') or key.startswith('note_') or key.startswith('video_'):
                data_dict = loader_data[key]
                logger.info(f"[Parser] 找到数据类型: {key}")
                break
        
        if data_dict:
            logger.info(f"[Parser] data_dict keys: {list(data_dict.keys())[:10]}")
            content = self._parse_data_dict(data_dict, item_id)
            return await self._try_api_supplement(content, item_id)
        
        # 遍历查找item_list
        logger.info(f"[Parser] 前缀匹配失败，遍历查找")
        for key, value in loader_data.items():
            if isinstance(value, dict):
                if 'videoInfoRes' in value or 'item_list' in value:
                    logger.info(f"[Parser] 在key '{key}' 中找到数据")
                    content = self._parse_data_dict(value, item_id)
                    return await self._try_api_supplement(content, item_id)
                if 'aweme_detail' in value:
                    logger.info(f"[Parser] 在key '{key}' 中找到aweme_detail")
                    return self._parse_aweme_detail(value['aweme_detail'], item_id)
        
        return None
    
    def _parse_state_json(self, data: Any, item_id: str) -> Optional[DouyinContent]:
        """解析 __INITIAL_STATE__ / __PRELOADED_STATE__ 格式"""
        if not isinstance(data, dict):
            return None
        
        # 提取 aweme_detail
        ad = data.get("aweme_detail")
        if ad:
            return self._parse_aweme_detail(ad, item_id)
        
        # 提取 videoInfoRes.item_list
        vir = data.get("videoInfoRes", data)
        if isinstance(vir, dict):
            item_list = vir.get("item_list", [])
            if item_list:
                return self._parse_data_dict({"item_list": item_list}, item_id)
        
        # 深度搜索 aweme_detail
        for key, value in data.items():
            if isinstance(value, dict):
                ad = value.get("aweme_detail")
                if ad:
                    return self._parse_aweme_detail(ad, item_id)
        
        return None
    
    async def _try_api_supplement(self, content, item_id) -> Optional[DouyinContent]:
        """尝试补充实况照片的视频数据
        
        规则：
        - 没有图片 → 返回原始 content
        - 已有视频 → 返回原始 content
        - API补充成功 → 返回 ANIMATED（含 video 配对）
        - API补充失败 → **仍然返回 IMAGE 类型**（不丢图片）
        """
        if not content:
            return None
        if not content.images:
            return content
        
        has_any_video = any(m.type == "video" for m in content.images)
        if has_any_video or content.content_type == ContentType.VIDEO:
            return content
        
        logger.info(f"[Parser] 尝试API补充实况照片视频数据...")
        api_content = await self._fetch_slides_via_api(item_id, self.USER_AGENTS[0])
        
        # API补充成功 → 配对 video 并升级为 ANIMATED
        if api_content and api_content.images:
            # 视频数据在 motion_photo_pairs 中，不在 images 里（images 里全是 type="image"）
            api_videos = [pair.video for pair in (api_content.motion_photo_pairs or [])]
            if api_videos:
                new_pairs = []
                vid_idx = 0
                for m in content.images:
                    if vid_idx < len(api_videos):
                        new_pairs.append(MotionPhotoPair(image=m, video=api_videos[vid_idx]))
                        vid_idx += 1
                content.motion_photo_pairs = new_pairs
                content.content_type = ContentType.ANIMATED
                logger.info(f"[Parser] API补充了 {len(api_videos)} 个实况视频配对")
                return content
        
        # API补充失败 → 返回 None，让上层继续尝试其他途径（如浏览器解析）
        logger.info(f"[Parser] API补充实况视频失败，由上层决定是否继续尝试其他途径")
        return None
    
    def _extract_json(self, html: str, start: int) -> Optional[dict]:
        """从指定位置提取JSON"""
        depth = 0
        in_string = False
        escape = False
        pos = start
        
        while pos < len(html):
            char = html[pos]
            
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif in_string:
                if char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    pos += 1
                    break
            
            pos += 1
        
        if pos > start and depth == 0:
            json_str = html[start:pos]
            # 清理JSON（合并两个正则，移除尾逗号）
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
            # 处理Unicode转义
            json_str = json_str.replace('\\u002F', '/')
            
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.info(f"[Parser] JSON解析失败: {e}")
        
        return None
    
    def _parse_data_dict(self, data_dict: dict, item_id: str) -> Optional[DouyinContent]:
        """解析数据字典"""
        content = DouyinContent(item_id=item_id)
        
        # 展平 aweme_detail 嵌套（iesdouyin分享页的数据结构）
        if "aweme_detail" in data_dict and isinstance(data_dict["aweme_detail"], dict):
            data_dict = data_dict["aweme_detail"]
        
        # 提取videoInfoRes
        video_info_res = data_dict.get("videoInfoRes", data_dict)
        item_list = video_info_res.get("item_list", [])
        
        if item_list:
            item_data = item_list[0]
        else:
            item_data = data_dict
        
        # 提取描述
        content.title = item_data.get("desc", "") or f"douyin_{item_id}"
        
        # 发布日期（命名用，P4-2）
        content.publish_date = _fmt_publish_date(item_data.get("create_time"))
        
        # 提取作者
        author = item_data.get("author", {})
        if isinstance(author, dict):
            content.author = author.get("nickname", "") or author.get("unique_id", "") or ""
        
        # 提取封面
        video_data = item_data.get("video", {})
        if isinstance(video_data, dict):
            cover = video_data.get("cover", {})
            if isinstance(cover, dict):
                cover_list = cover.get("url_list", [])
                content.cover = cover_list[0] if cover_list else ""
        
        # 检查是否有images（图文/实况照片）
        images_data = item_data.get("images", [])
        if images_data and isinstance(images_data, list):
            logger.info(f"[Parser] 找到 {len(images_data)} 张图片")
            
            # 调试：打印第一张图片的keys
            if images_data and isinstance(images_data[0], dict):
                logger.info(f"[Parser] 图片数据keys: {list(images_data[0].keys())}")
            
            has_live_photo = False
            
            # 方案1: 检查顶层字段（优先级最高）
            top_level_has_live = item_data.get("has_live_photo", False)
            top_level_live_urls = item_data.get("live_photo_urls", []) or item_data.get("live_photos", [])
            
            if top_level_has_live or top_level_live_urls:
                has_live_photo = True
                logger.info(f"[Parser] 从顶层字段检测到实况照片")
                # 获取对应的图片URL列表
                img_urls = [u for u in (item_data.get("image_urls", []) or item_data.get("images", [])) if isinstance(u, str)]
                video_urls = [u for u in top_level_live_urls if isinstance(u, str)]
                # 按索引配对
                for i, img_url in enumerate(img_urls):
                    content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
                    if i < len(video_urls):
                        pair_img = MediaItem(url=img_url, type="image", file_ext="jpg")
                        pair_vid = MediaItem(url=video_urls[i], type="video", file_ext="mp4")
                        content.motion_photo_pairs.append(MotionPhotoPair(image=pair_img, video=pair_vid))
            else:
                # 方案2: 检查 images 数组中的 video 字段
                for img in images_data:
                    if not isinstance(img, dict):
                        continue
                    
                    url_list = img.get("url_list", [])
                    if not url_list:
                        continue
                    
                    img_url = url_list[-1] if len(url_list) > 1 else url_list[0]
                    
                    # 检查是否有 video 字段（实况照片的关键字段）
                    video = img.get("video", {})
                    if video and isinstance(video, dict):
                        play_addr = video.get("play_addr", {})
                        if isinstance(play_addr, dict):
                            v_urls = play_addr.get("url_list", [])
                            if v_urls:
                                has_live_photo = True
                                logger.info(f"[Parser] 从images数组检测到实况照片")
                                content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
                                pair_img = MediaItem(url=img_url, type="image", file_ext="jpg")
                                pair_vid = MediaItem(url=v_urls[-1], type="video", file_ext="mp4")
                                content.motion_photo_pairs.append(MotionPhotoPair(image=pair_img, video=pair_vid))
                                continue
                    
                    # 普通图片
                    content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
            
            content.content_type = ContentType.ANIMATED if has_live_photo else ContentType.IMAGE
        
        # 检查video（只有在没有images时才设置为VIDEO）
        elif video_data and isinstance(video_data, dict):
            content.content_type = ContentType.VIDEO
            
            # 提取video_id用于获取无水印视频
            video_play_id = self._extract_video_id_from_html(str(video_data))
            
            if video_play_id:
                logger.info(f"[Parser] 找到video_id: {video_play_id}")
                # 使用无水印API
                content.video_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={video_play_id}&ratio=1080p&line=0"
                content.video_quality = "1080p"
            else:
                # 回退到原始方法
                play_addr = video_data.get("play_addr", {})
                if isinstance(play_addr, dict):
                    url_list = play_addr.get("url_list", [])
                    if url_list:
                        video_url = url_list[-1] if len(url_list) > 1 else url_list[0]
                        # 将playwm替换为play
                        content.video_url = video_url.replace('/playwm/', '/play/')
                        content.video_url_watermark = video_url
        
        return content if (content.video_url or content.images) else None
    
    def _parse_aweme_detail(self, aweme_detail: dict, item_id: str) -> Optional[DouyinContent]:
        """解析aweme_detail数据"""
        content = DouyinContent(item_id=item_id)
        
        content.title = aweme_detail.get("desc", "") or f"douyin_{item_id}"
        content.publish_date = _fmt_publish_date(aweme_detail.get("create_time"))
        
        author = aweme_detail.get("author", {})
        if isinstance(author, dict):
            content.author = author.get("nickname", "") or author.get("unique_id", "") or ""
        
        # 检查images
        images_data = aweme_detail.get("images", [])
        if images_data and isinstance(images_data, list):
            logger.info(f"[Parser] API返回 {len(images_data)} 张图片")
            has_live_photo = False
            
            for img in images_data:
                if not isinstance(img, dict):
                    continue
                url_list = img.get("url_list", [])
                img_url = None
                if url_list:
                    img_url = url_list[-1] if len(url_list) > 1 else url_list[0]
                    content.images.append(MediaItem(url=img_url, type="image", file_ext="jpg"))
                
                # 检查实况照片video字段
                video = img.get("video", {})
                if video and isinstance(video, dict):
                    play_addr = video.get("play_addr", {})
                    if isinstance(play_addr, dict):
                        v_urls = play_addr.get("url_list", [])
                        if v_urls and img_url:
                            has_live_photo = True
                            pair_img = MediaItem(url=img_url, type="image", file_ext="jpg")
                            pair_vid = MediaItem(url=v_urls[-1], type="video", file_ext="mp4")
                            content.motion_photo_pairs.append(MotionPhotoPair(image=pair_img, video=pair_vid))
            
            content.content_type = ContentType.ANIMATED if has_live_photo else ContentType.IMAGE
        
        # 检查video（仅当没有图片时才设置为VIDEO）
        # 图文优先：如果已经有images，不再检查video字段
        if not content.images:
            video_data = aweme_detail.get("video", {})
            if video_data and isinstance(video_data, dict):
                content.content_type = ContentType.VIDEO
                
                cover = video_data.get("cover", {})
                if isinstance(cover, dict):
                    cover_list = cover.get("url_list", [])
                    content.cover = cover_list[0] if cover_list else ""
                
                # 提取video_id
                video_play_id = video_data.get("play_addr", {}).get("uri", "")
                
                if video_play_id:
                    content.video_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={video_play_id}&ratio=1080p&line=0"
                else:
                    play_addr = video_data.get("play_addr", {})
                    if isinstance(play_addr, dict):
                        url_list = play_addr.get("url_list", [])
                        if url_list:
                            video_url = url_list[-1] if len(url_list) > 1 else url_list[0]
                            content.video_url = video_url.replace('/playwm/', '/play/')
        
        return content if (content.video_url or content.images) else None
    
    async def _extract_from_html_fallback(self, html: str, item_id: str) -> Optional[DouyinContent]:
        """从HTML直接提取数据（备用方法）
        
        尝试顺序：
        1. og:video / og:image meta 标签
        2. JSON-LD (application/ld+json) 
        3. video_id 正则提取
        4. playwm URL 提取
        5. 通用 video/mp4 URL 提取
        """
        content = DouyinContent(item_id=item_id)
        
        # --- 方案1: og meta 标签 ---
        og_video = re.search(r'<meta[^>]*property=["\']og:video[^>]*content=["\']([^"\']+)["\']', html)
        og_title = re.search(r'<meta[^>]*property=["\']og:title[^>]*content=["\']([^"\']+)["\']', html)
        og_image = re.search(r'<meta[^>]*property=["\']og:image[^>]*content=["\']([^"\']+)["\']', html)
        
        if og_video:
            video_url = og_video.group(1).replace('\\u002F', '/').replace('/playwm/', '/play/')
            content.content_type = ContentType.VIDEO
            content.video_url = video_url
            content.title = og_title.group(1) if og_title else f"douyin_{item_id}"
            if og_image:
                content.cover = og_image.group(1)
            logger.info(f"[Parser] 从og:video提取到URL")
            return content
        
        # --- 方案2: JSON-LD ---
        ld_match = re.search(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if ld_match:
            try:
                ld_data = json.loads(ld_match.group(1))
                if isinstance(ld_data, dict):
                    # 提取视频URL
                    for field in ('contentUrl', 'embedUrl', 'url'):
                        if field in ld_data:
                            video_url = ld_data[field].replace('\\u002F', '/')
                            content.content_type = ContentType.VIDEO
                            content.video_url = video_url
                            content.title = ld_data.get('name', '') or ld_data.get('description', '') or f"douyin_{item_id}"
                            logger.info(f"[Parser] 从JSON-LD提取到URL")
                            return content
                    # 检查hasPart
                    for part in ld_data.get('hasPart', []):
                        if isinstance(part, dict):
                            for field in ('contentUrl', 'embedUrl', 'url'):
                                if field in part:
                                    video_url = part[field].replace('\\u002F', '/')
                                    content.content_type = ContentType.VIDEO
                                    content.video_url = video_url
                                    content.title = part.get('name', '') or f"douyin_{item_id}"
                                    logger.info(f"[Parser] 从JSON-LD hasPart提取到URL")
                                    return content
            except json.JSONDecodeError:
                pass
        
        # --- 方案3: video_id ---
        video_play_id = self._extract_video_id_from_html(html)
        
        if video_play_id:
            logger.info(f"[Parser] 从HTML提取到video_id: {video_play_id}")
            content.content_type = ContentType.VIDEO
            content.video_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={video_play_id}&ratio=1080p&line=0"
            content.title = f"douyin_{item_id}"
            return content
        
        # --- 方案4: playwm URL ---
        playwm_pattern = r'https?:[^"]*playwm[^"]*'
        playwm_matches = re.findall(playwm_pattern, html)
        
        if playwm_matches:
            video_url = playwm_matches[0].replace('\\u002F', '/')
            content.content_type = ContentType.VIDEO
            content.video_url = video_url.replace('/playwm/', '/play/')
            content.video_url_watermark = video_url
            content.title = f"douyin_{item_id}"
            return content
        
        # --- 方案5: 任何 video/mp4 URL ---
        mp4_urls = re.findall(r'https?:[^"\'<>]+\.mp4[^"\'<>]*', html)
        if mp4_urls:
            video_url = mp4_urls[0].replace('\\u002F', '/')
            # 排除带水印的旧有逻辑
            content.content_type = ContentType.VIDEO
            content.video_url = video_url.replace('/playwm/', '/play/')
            content.title = f"douyin_{item_id}"
            logger.info(f"[Parser] 从mp4 URL提取到: {video_url[:60]}...")
            return content
        
        return None
    
    def _extract_video_id_from_html(self, html: str) -> Optional[str]:
        """从HTML中提取video_id
        
        策略：
        1. 优先精确匹配 v0xxx/v1xxx 格式的 play ID（真正的播放ID）
        2. 通用模式匹配后做严格验证（不含 / . : # ? 且非 URL）
        """
        def _is_valid_play_id(vid: str) -> bool:
            """验证是否为真正的video play ID"""
            if not vid or len(vid) < 10:
                return False
            # 排除URL、文件路径
            if any(c in vid for c in ('/', ':', '.', '#', '?', '&', '%')):
                return False
            # 必须以 v0/v1/v2/v3 开头
            if vid.startswith(('v0', 'v1', 'v2', 'v3')):
                return True
            return False
        
        # 方案1: 先精确匹配 v0xxx 格式（最可靠）
        v_patterns = [
            r'(?:video_id|vid|uri)\s*:\s*"(v0[0-9][0-9][a-zA-Z0-9]{15,})"',
            r'(?:video_id|vid|uri)\s*:\s*"(v[0-9][0-9][0-9][a-zA-Z0-9]{15,})"',
            r'("v0[0-9][0-9][a-zA-Z0-9]{15,}")',
        ]
        for pat in v_patterns:
            m = re.search(pat, html)
            if m:
                vid = m.group(1).strip('"')
                if _is_valid_play_id(vid):
                    return vid
        
        # 方案2: 通用模式 + 严格验证
        patterns = [
            r'"video_id"\s*:\s*"([^"]+)"',
            r"'video_id'\s*:\s*'([^']+)'",
            r'videoId["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_]{10,})',
            r'vid["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_]{10,})',
            r'video_id=([^&"\'\s]+)',
            r'"vid"\s*:\s*"([^"]+)"',
            r'playId["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_]{10,})',
            r'"playId"\s*:\s*"([^"]+)"',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match and match[1]:
                video_id = match[1]
                if _is_valid_play_id(video_id):
                    return video_id
        
        # 方案3: 全局搜索 v0xxx 模式
        v_match = re.search(r'(v0[0-9][0-9][a-zA-Z0-9]{15,})', html)
        if v_match:
            return v_match.group(1)
        
        return None


_parser = OptimizedOfficialParser()


def parse_url(input_text: str) -> Optional[str]:
    """从任意文本中提取抖音链接"""
    patterns = [
        r'https?://[^\s]*(?:douyin|iesdouyin|v\.douyin)[^\s]*',
        r'(?:douyin|iesdouyin|v\.douyin)\.com/[\w\-\.]+[^\s]*',
        r'v\.douyin\.com/[\w\-]+',
        r'douyin\.com/video/\d+',
        r'douyin\.com/note/\d+',
        r'douyin\.com/slides/\d+',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, input_text)
        if match:
            url = match.group(0).rstrip('/').rstrip('"').rstrip("'").strip()
            if not url.lower().startswith('http'):
                url = 'https://' + url
            return url
    
    return None


_last_parse_result = {}  # 调试用：记录最近一次解析结果


# ======================================================================
# 浏览器后端（douyin_browser）
# ======================================================================
#
# 背景：抖音现行风控（ArgusSecurityPlugin）会校验浏览器运行时产生的
# 动态凭据。2026-09-26 实测，纯 HTTP 方案全部 403：
#   · 官方页面解析（RENDER_DATA / __INITIAL_STATE__ 已从响应中移除）
#   · aweme/detail、aweme/post 接口（ArgusSecurityPlugin 拦截）
#   · F2 库 + 完整登录 Cookie（66 条，含 sessionid/UIFID）仍 403
#   · curl_cffi 伪装 Chrome/Edge TLS 指纹仍 403
#
# 因此新增 douyin_browser 作为首选后端，用真实 Chromium 完成解析。
# 旧路径保留为兜底，避免新后端出问题时功能完全不可用。
#
# 详见 docs/抖音路线验证报告-2026-09-26.md

_browser_instance = None      # 全局共享的 DouyinBrowser（避免重复启动 Chromium）
_browser_lock = None         # 保护 _browser_instance 的创建
_browser_disabled = False    # 熔断标记：浏览器后端连续失败后不再重试


def _get_browser_lock():
    """惰性创建 asyncio.Lock（避免 import 时绑定事件循环）"""
    global _browser_lock
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    return _browser_lock


async def get_browser():
    """
    获取全局共享的 DouyinBrowser 实例

    Chromium 启动约 1~2 秒，重复启动会拖慢每次解析，
    因此全局复用同一个实例，由 server 启动/关闭时统一管理生命周期。
    """
    global _browser_instance

    if _browser_instance is not None:
        return _browser_instance

    async with _get_browser_lock():
        if _browser_instance is None:
            from .douyin_browser import DouyinBrowser
            _browser_instance = DouyinBrowser(headless=True)
            await _browser_instance.start()
            logger.info("[Fetch] 抖音浏览器后端已启动")
    return _browser_instance


async def close_browser():
    """关闭全局浏览器实例（程序退出时调用）"""
    global _browser_instance

    if _browser_instance is None:
        return

    try:
        await _browser_instance.close()
        logger.info("[Fetch] 抖音浏览器后端已关闭")
    except Exception as e:
        logger.warning(f"[Fetch] 关闭浏览器失败: {e}")
    finally:
        _browser_instance = None


# ==================================================================
# 抖音登录
# ==================================================================
# 登录态本身由浏览器 profile 目录里的 cookie 维持，进程内只缓存「流程状态」。
#
# 关键约束：Chromium 会独占 profile 目录（SingletonLock），
# 有头登录窗口和无头下载实例不能同时存在。所以登录流程必须是：
#
#     关掉无头实例 → 开有头窗口让用户扫码 → 关掉有头窗口
#                    → 无头实例留到下次下载时按需重启
#
# 已知限制：登录期间若有下载任务在跑，两者会争抢同一个 profile。
# 因此 douyin_start_login() 会先检查队列是否空闲，不空闲直接拒绝。
# 后续做后台定时轮询时，这里要升级成读写锁
# （下载持读锁、登录持写锁），否则轮询任务会打断用户扫码。

# 登录流程状态
LOGIN_IDLE = "idle"            # 未开始
LOGIN_WAITING = "waiting"      # 已开窗口，等用户扫码
LOGIN_SUCCESS = "success"      # 登录成功
LOGIN_FAILED = "failed"        # 出错（含用户把窗口关了）
LOGIN_TIMEOUT = "timeout"      # 超时未扫码
LOGIN_CANCELLED = "cancelled"  # 用户主动取消

_login_state: dict = {
    "status": LOGIN_IDLE,
    "message": "",
    # started_at 是 time.time()（墙钟），只用来给前端显示「已用多少秒」
    # started_mono 是 time.monotonic()（单调钟），只用来算 deadline
    # 两者不能混用：早先拿墙钟去和单调钟比，算出 17 亿秒，
    # 结果超时永不触发，登录窗口一直挂着，把后续所有登录请求都堵死。
    "started_at": 0.0,
    "started_mono": 0.0,
    "elapsed": 0,
}
_login_task: Optional[asyncio.Task] = None


def _login_snapshot() -> dict:
    """给前端看的登录流程状态快照（waiting 时实时算已用秒数）"""
    snap = {k: v for k, v in _login_state.items() if k != "started_mono"}
    if snap["status"] == LOGIN_WAITING:
        snap["elapsed"] = int(time.time() - snap["started_at"])
    return snap


def is_login_running() -> bool:
    """登录流程是否正在跑"""
    return _login_task is not None and not _login_task.done()


def _login_message(deadline: float) -> str:
    """扫码提示文案，带实时剩余秒数（deadline 必须来自单调钟）"""
    left = max(0, int(deadline - time.monotonic()))
    return f"请在弹出的浏览器窗口里扫码登录抖音（还剩 {left} 秒）"


def _active_download_count() -> int:
    """在跑 + 排队的下载任务数（登录要独占 profile，不能和它们并行）"""
    try:
        from .download_queue import download_queue
        st = download_queue.get_queue_status()
        return int(st.get("downloading", 0)) + int(st.get("pending", 0))
    except Exception as e:
        logger.debug(f"[Login] 读取队列状态失败，按 0 处理: {e}")
        return 0


async def douyin_login_status() -> dict:
    """
    查询抖音登录态（走抖音自己的接口判定，权威）

    不能只看 cookie：未登录访客抖音也会发占位 sessionid
    （实测 4 个 cookie 全是同一个哈希值），只看 cookie 会误判。

    Returns:
        {logged_in, login_running, status, message, elapsed, detail}
    """
    result: dict = {
        "logged_in": False,
        "login_running": is_login_running(),
        "detail": "",
        **_login_snapshot(),
    }

    browser = _browser_instance
    if browser is None:
        # 登录流程会为了腾出 profile 关掉后台无头实例。
        # 万一还没重启回来，别把「刚登录成功」误报成「未登录」——
        # 实测踩过：扫码成功后 status 返回 logged_in=false，
        # 界面上立刻又变回未登录，用户会以为扫码没生效。
        if _login_state.get("status") == LOGIN_SUCCESS:
            result["logged_in"] = True
            result["detail"] = "（登录流程已确认，后台浏览器稍后恢复）"
        else:
            result["message"] = result["message"] or "后台浏览器未启动，请稍候重试"
        return result

    try:
        logged, detail = await browser.check_login_via_api()
        result["logged_in"] = logged
        result["detail"] = detail
    except Exception as e:
        logger.warning(f"[Login] 读取登录态失败: {e}")
        result["message"] = f"读取登录态失败：{e}"
    return result


async def douyin_start_login(timeout: int = 300) -> dict:
    """
    启动抖音扫码登录（转后台任务，立即返回，不阻塞接口）

    Args:
        timeout: 等待扫码的最长秒数

    Returns:
        {ok, status, message, elapsed}；ok=False 时 error 说明原因
    """
    global _login_task

    if is_login_running():
        return {"ok": True, "already_running": True, **_login_snapshot()}

    busy = _active_download_count()
    if busy:
        return {
            "ok": False,
            "error": f"当前有 {busy} 个下载任务在进行，请等下载结束后再登录。"
                     "（登录窗口和下载共用同一个浏览器配置，不能并行）",
            **_login_snapshot(),
        }

    # 订阅自动轮询正在抓主页时也不能开登录窗 —— 它和下载一样占着
    # 同一个 Chromium profile。检查和下面的状态更新之间没有 await，
    # 所以轮询那边「检查登录状态 → 置 running」这段同样无 await，
    # 两边不会在同一个事件循环里互相穿过。
    from . import poller
    if poller.is_round_running():
        return {
            "ok": False,
            "error": "正在自动检查订阅更新，等这一轮结束再登录。"
                     "（约十几秒，可稍后重试）",
            **_login_snapshot(),
        }

    _login_state.update(
        status=LOGIN_WAITING,
        message="正在准备浏览器…",
        started_at=time.time(),      # 墙钟：给前端显示已用秒数
        started_mono=time.monotonic(),  # 单调钟：算 deadline
        elapsed=0,
    )
    _login_task = asyncio.create_task(_run_login(timeout))
    logger.info("[Login] 已启动抖音登录流程")
    return {"ok": True, **_login_snapshot()}


async def _run_login(timeout: int) -> None:
    """登录流程主体（跑在后台任务里）"""
    from .douyin_browser import DouyinBrowser

    headful = None
    try:
        # 1. 先释放 profile 占用。
        #    Chromium 关闭后不会立刻释放 SingletonLock，留一点余量。
        _login_state["message"] = "正在释放后台浏览器…"
        await close_browser()
        await asyncio.sleep(1.5)

        # 2. 开有头窗口
        _login_state["message"] = "正在打开浏览器窗口…"
        headful = DouyinBrowser(headless=False)
        await headful.start()
        await headful.open_login_page()

        # 3. 等用户扫码（只轮询 cookie，不重复导航页面）
        #    deadline 从流程开始算起，保证「最多等 timeout 秒」是准确的总数。
        #    早先从开完窗口才起算，导致开窗口那几秒不计入，
        #    前端显示的已用秒数会超出承诺（实测 timeout=8 却显示 12 秒）。
        deadline = _login_state["started_mono"] + timeout
        _login_state["message"] = _login_message(deadline)
        logger.info(f"[Login] 登录窗口已打开，等待扫码（{timeout} 秒）")

        tick = 0
        while time.monotonic() < deadline:
            # 用接口判定而不是 cookie：未登录访客也有占位 sessionid，
            # 只看 cookie 会一进来就误判成「已登录」。
            try:
                logged, detail = await headful.check_login_via_api()
            except Exception as e:
                # 用户把窗口关了，或浏览器崩了
                _login_state.update(
                    status=LOGIN_FAILED,
                    message="登录窗口已被关闭或网络异常，请重新点击「登录抖音」",
                )
                logger.warning(f"[Login] 探测登录态失败: {e}")
                return

            if logged:
                elapsed = int(time.time() - _login_state["started_at"])

                # 先关有头窗口把 profile 让出来。
                # Chromium 独占 profile 目录，不关的话下面 get_browser()
                # 拉起的无头实例会和它抢同一份数据。
                if headful is not None:
                    try:
                        await headful.close()
                    except Exception as e:
                        logger.debug(f"[Login] 提前关闭登录窗口失败: {e}")
                    headful = None

                # 重新拉起后台无头实例。登录流程一开始为了腾 profile
                # 把它关了，不拉回来的话：
                #   1. /login/status 因为拿不到浏览器会误报「未登录」
                #      （实测登录成功后立刻返回 logged_in=false）
                #   2. 用户登录完还得等下一次调用才启动 Chromium
                # 代价约 2~3 秒，发生在扫码成功之后，不影响扫码体验。
                verify, vdetail = True, "（登录流程已确认，未能复核）"
                try:
                    await get_browser()
                    verify, vdetail = await _browser_instance.check_login_via_api()
                except Exception as e:
                    logger.warning(f"[Login] 登录后恢复后台浏览器失败: {e}")

                _login_state.update(
                    status=LOGIN_SUCCESS,
                    message=f"登录成功（{vdetail}）",
                    elapsed=elapsed,
                )
                logger.info(f"[Login] 抖音登录成功 — {vdetail}（复核 {verify}）")
                return

            tick += 1
            _login_state["elapsed"] = int(time.time() - _login_state["started_at"])
            # 每约 9 秒刷新一次剩余时间提示
            if tick % 3 == 0:
                _login_state["message"] = _login_message(deadline)
            await asyncio.sleep(3)

        _login_state.update(
            status=LOGIN_TIMEOUT,
            message=f"{timeout} 秒内没有完成登录，已关闭登录窗口，请重试",
            elapsed=int(time.time() - _login_state["started_at"]),
        )
        logger.warning("[Login] 等待扫码超时")

    except asyncio.CancelledError:
        _login_state.update(
            status=LOGIN_CANCELLED, message="已取消登录",
        )
        logger.info("[Login] 登录流程被取消")
        raise
    except Exception as e:
        logger.error(f"[Login] 登录流程出错: {e}", exc_info=True)
        _login_state.update(status=LOGIN_FAILED, message=f"登录失败：{e}")
    finally:
        if headful is not None:
            try:
                await headful.close()
            except Exception as e:
                logger.debug(f"[Login] 关闭登录窗口失败: {e}")
        _login_task = None


async def douyin_cancel_login() -> dict:
    """取消正在进行的登录流程"""
    if not is_login_running():
        return {"ok": True, "already_stopped": True, **_login_snapshot()}

    _login_task.cancel()
    for _ in range(30):          # 最多等 3 秒让取消生效
        await asyncio.sleep(0.1)
        if not is_login_running():
            break
    return {"ok": True, **_login_snapshot()}


async def douyin_logout() -> dict:
    """退出抖音登录（清掉 profile 里的登录 cookie）"""
    if is_login_running():
        return {"ok": False, "error": "登录流程进行中，请先取消再退出"}

    browser = _browser_instance
    if browser is None:
        return {"ok": False, "error": "后台浏览器未启动，无法退出登录"}

    try:
        cleared = await browser.clear_login_cookies()
    except Exception as e:
        logger.error(f"[Login] 退出登录失败: {e}")
        return {"ok": False, "error": f"退出登录失败：{e}"}

    _login_state.update(
        status=LOGIN_IDLE, message="已退出登录",
        started_at=0.0, started_mono=0.0, elapsed=0,
    )
    logger.info(f"[Login] 已退出登录（清除 {cleared} 条 cookie）")
    return {"ok": True, "cleared": cleared, **_login_snapshot()}



async def _fetch_content_browser(input_text: str) -> Optional[DouyinContent]:
    """
    用浏览器后端解析抖音视频

    与旧后端的区别：
      · 旧后端返回 video_url，由 download_content 用 httpx 下载
      · 浏览器后端的流地址带签名且有时效，httpx 直连会拿到 351 字节的
        HTML 错误页，必须由浏览器在页面上下文中下载

    因此这里只填充元数据，把下载交给 _browser_download_pending，
    由 download_content 识别后走浏览器下载分支。

    Args:
        input_text: 抖音链接或分享文案

    Returns:
        DouyinContent；失败返回 None（交给调用方走兜底）
    """
    from .douyin_browser import parse_video_url

    browser = await get_browser()

    # 短链需要先解析出 aweme_id
    aweme_id = await parse_video_url(input_text, browser=browser)
    if not aweme_id:
        logger.info("[Fetch:browser] 未能解析出作品 ID")
        return None

    item = await browser.resolve_stream(aweme_id)

    content = DouyinContent(
        item_id=item.aweme_id,
        content_type=ContentType.VIDEO,
        title=item.title or f"douyin_{item.aweme_id}",
        author=item.author or "",
        cover=item.cover or "",
        video_url=item.stream_url,
        file_ext="mp4",
        backend="browser",
        author_sec_uid=item.author_sec_uid or "",
        stream_size=item.size,
        publish_date=item.publish_date or "",
    )

    logger.info(
        f"[Fetch:browser] 解析成功 {aweme_id} "
        f"{item.size:,} bytes | {item.title[:40]} | 作者={item.author or '-'}"
    )
    return content


def _is_browser_backend(content: DouyinContent) -> bool:
    """判断该内容是否由浏览器后端解析（需走浏览器下载）"""
    return getattr(content, "backend", "legacy") == "browser"


async def _browser_download_pending(
    content: DouyinContent,
    output_dir: Path,
    task_id: str = None,
    progress_callback=None,
    rename_strategy: str | None = None,
) -> List[Path]:
    """
    浏览器后端下载

    命名规则（P4-2，2026-09-27）：`标题 2026-09-27.mp4`；
    拿不到发布日期回落 `douyin_<item_id>.mp4`。
    """
    browser = await get_browser()

    video_dir = get_download_subdir('videos')
    filename = build_download_base(content)
    target = video_dir / f"{filename}.mp4"

    # 已存在且未指定覆盖时，直接跳过。
    # 旧命名 douyin_<item_id>.mp4 也算已存在 —— 切新命名后不许重下出第二份
    if rename_strategy != "overwrite":
        existing = _existing_target([
            target,
            video_dir / f"douyin_{content.item_id}.mp4",
        ])
        if existing:
            logger.info(f"[Download:browser] 已存在，跳过: {existing.name}")
            if progress_callback:
                progress_callback(1.0)
            if task_id:
                from .download_queue import download_queue
                download_queue.update_progress(task_id, 1.0)
            content.file_path = str(existing)
            return [existing]

    logger.info(f"[Download:browser] 开始下载 {content.item_id}")

    def _on_progress(done: int, total: int):
        if total <= 0:
            return
        ratio = min(done / total, 1.0)
        if progress_callback:
            progress_callback(ratio)
        if task_id:
            from .download_queue import download_queue
            download_queue.update_progress(task_id, ratio, done, total)

    # 注意：流地址有短时效签名（约 5~15 秒），不能跨请求复用。
    # 因此这里不再传入 content.video_url，而是让 download() 内部
    # 现解析现用——这是"签名过期自动换 URL 续传"逻辑的前提。
    path = await browser.download(
        content.item_id,
        video_dir,
        filename=filename,
        progress_callback=_on_progress,
    )

    content.file_path = str(path)
    logger.info(f"[Download:browser] 完成: {path.name}")
    return [path]


async def fetch_content(input_text: str) -> DouyinContent:
    """
    解析抖音链接，返回内容信息

    解析优先级（2026-09-26 调整）：
    1. 浏览器后端（douyin_browser）—— 当前唯一可靠路径
    2. 旧官方页面解析 —— 保留兜底
    3. 第三方 API —— 保留兜底
    """
    global _last_parse_result, _browser_disabled

    url = parse_url(input_text)
    if not url:
        raise ValueError("未找到抖音链接")

    content = None

    # 1. 浏览器后端（首选）
    if not _browser_disabled:
        try:
            content = await _fetch_content_browser(input_text)
        except Exception as e:
            logger.warning(f"[Fetch:browser] 解析失败: {type(e).__name__}: {e}")
            # 连续失败后熔断，避免每次解析都卡在浏览器启动上
            content = None
    else:
        logger.info("[Fetch:browser] 已熔断，跳过浏览器后端")

    # 2. 兜底：旧官方解析
    if not content:
        content = await _parser.parse(url)

    # 3. 兜底：第三方 API
    if not content or (not content.video_url and not content.images):
        try:
            from .douyin_third_party import parse_with_third_party
            content = await parse_with_third_party(url)
        except Exception as e:
            logger.info(f"[Fetch] 第三方解析失败: {e}")

    if not content:
        raise ValueError("解析失败")

    if not content.video_url and not content.images:
        raise ValueError("未找到视频或图片地址")

    # 保存调试信息
    _last_parse_result = {
        "url": url[:200],
        "backend": "browser" if _is_browser_backend(content) else "legacy",
        "content_type": str(content.content_type.value) if content.content_type else "?",
        "video_url": str(content.video_url)[:200] if content.video_url else None,
        "video_url_watermark": str(content.video_url_watermark)[:200] if content.video_url_watermark else None,
        "title": str(content.title)[:100] if content.title else None,
        "author": str(content.author)[:100] if content.author else None,
        "cover": str(content.cover)[:200] if content.cover else None,
        "image_count": len(content.images) if content.images else 0,
        "has_motion_photos": bool(content.motion_photo_pairs),
    }
    logger.info(
        f"[Fetch] 解析结果: backend={_last_parse_result['backend']}, "
        f"type={_last_parse_result['content_type']}, "
        f"video_url={str(_last_parse_result['video_url'])[:100]}"
    )

    return content


async def download_content(
    content: DouyinContent,
    output_dir: str | Path = "./downloads",
    merge_motion_photo: bool | None = None,
    apple_live_photo: bool = False,
    task_id: str = None,
    progress_callback=None,
    rename_strategy: str | None = None
) -> List[Path]:
    """
    下载内容
    
    Args:
        content: 抖音内容对象
        output_dir: 输出目录（已废弃，现在使用分类子目录）
        merge_motion_photo: 是否自动合并实况照片为Motion Photo格式（None时从配置读取）
        apple_live_photo: 是否同时生成Apple Live Photo格式（适用于iPhone）
        task_id: 任务ID（用于暂停/取消检测）
        progress_callback: 进度回调函数
        rename_strategy: 文件重名策略 (skip/overwrite/rename)，None则从配置读取
    """
    from .exceptions import PauseException, CancelException

    # 从配置读取默认值
    if merge_motion_photo is None:
        from .utils import load_config
        cfg = load_config()
        merge_motion_photo = cfg.get('general', {}).get('motion_photo_default', True)

    # 重名策略也在这里定死：下面各分支的「已存在跳过（含旧命名文件）」
    # 预检要用真实生效值，不能一路传 None（None 意味着各处自己猜）
    if rename_strategy is None:
        from .utils import load_config
        cfg = load_config()
        rename_strategy = cfg.get('general', {}).get('rename_strategy', 'skip')
    
    # 确保output_dir是Path对象
    output_dir = Path(output_dir)

    downloaded = []

    # 浏览器后端：流地址带签名，必须由浏览器在页面上下文中下载，
    # 用 httpx 直连只会拿到 351 字节的 HTML 错误页。
    if _is_browser_backend(content):
        if content.content_type != ContentType.VIDEO:
            logger.info("[Download:browser] 浏览器后端暂只支持视频，"
                        "其他类型回退旧逻辑")
        else:
            return await _browser_download_pending(
                content,
                output_dir,
                task_id=task_id,
                progress_callback=progress_callback,
                rename_strategy=rename_strategy,
            )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    }
    
    async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers=headers) as client:
        
        if content.content_type == ContentType.VIDEO:
            # 视频下载
            download_url = content.video_url or content.video_url_watermark
            if not download_url:
                raise ValueError("无可用视频下载地址")
            
            if not content.video_url and content.video_url_watermark:
                logger.warning(" [!]  无法获取无水印视频，将下载带水印版本")
            
            video_dir = get_download_subdir('videos')
            base = build_download_base(content)
            filepath = video_dir / f"{base}.{content.file_ext}"

            # 已存在（含旧命名 douyin_<id>.<ext>）且未指定覆盖 → 跳过，
            # 旧命名文件不许被下成第二份
            existing = None
            if rename_strategy != "overwrite":
                existing = _existing_target([
                    filepath,
                    video_dir / f"douyin_{content.item_id}.{content.file_ext}",
                ])
            if existing:
                logger.info(f"[Download] 已存在，跳过: {existing.name}")
                downloaded.append(existing)
                content.file_path = str(existing)
            else:
                logger.info(f"[Download] 开始下载视频: {filepath.name}")
                await download_file(client, download_url, filepath, task_id, progress_callback, rename_strategy=rename_strategy)
                downloaded.append(filepath)
                content.file_path = str(filepath)
                logger.info(f"[Download] 下载完成: {filepath}")
        
        elif content.content_type == ContentType.ANIMATED and merge_motion_photo:
            # 实况照片：逐对下载并合并为 Motion Photo
            from .motion_photo import create_motion_photo
            
            animated_dir = get_download_subdir('animated')
            
            pairs = content.motion_photo_pairs
            if not pairs:
                # 兜底：从 images 列表重建配对（兼容旧逻辑）
                current_img = None
                for item in content.images:
                    if item.type == "image":
                        current_img = item
                    elif item.type == "video" and current_img:
                        pairs.append(MotionPhotoPair(image=current_img, video=item))
                        current_img = None
            
            total = len(pairs)
            logger.info(f"[Download] 检测到 {total} 对实况照片，将逐个合并为 Motion Photo")
            base = build_download_base(content)
            
            for i, pair in enumerate(pairs):
                # 检查是否暂停/取消
                from .utils import check_download_status
                check_download_status(task_id)
                
                pair_label = f"{i+1}/{total}"
                img_path = animated_dir / f"{base}_photo_{i+1}.jpg"
                vid_path = animated_dir / f"{base}_photo_{i+1}.mp4"
                output_file = animated_dir / f"{base}_motion_{i+1}.jpg"
                
                # 跳过已下载的motion文件（旧命名 douyin_<id>_motion_N 也算已存在）
                hit = _existing_target([
                    output_file,
                    animated_dir / f"douyin_{content.item_id}_motion_{i+1}.jpg",
                ])
                if hit:
                    logger.info(f"[Download] [{pair_label}] 已存在，跳过: {hit.name}")
                    downloaded.append(hit)
                    continue
                
                # 下载图片
                logger.info(f"[Download] [{pair_label}] 下载图片...")
                await download_file(client, pair.image.url, img_path, task_id, rename_strategy=rename_strategy)
                
                # 检查是否需要 WebP -> JPEG 转换
                with open(img_path, 'rb') as f:
                    header = f.read(4)
                if header[:4] == b'RIFF':
                    logger.info(f"[Download] [{pair_label}] WebP -> JPEG 转换...")
                    try:
                        from PIL import Image
                        img = Image.open(img_path)
                        img.convert('RGB').save(img_path, 'JPEG')
                    except Exception as e:
                        logger.info(f"[Download] [{pair_label}] 转换失败: {e}")
                
                # 下载视频
                logger.info(f"[Download] [{pair_label}] 下载视频...")
                await download_file(client, pair.video.url, vid_path, task_id, rename_strategy=rename_strategy)
                
                # 合并为 Motion Photo
                output_file = animated_dir / f"{base}_motion_{i+1}.jpg"
                try:
                    create_motion_photo(img_path, vid_path, output_file)
                    img_path.unlink(missing_ok=True)
                    vid_path.unlink(missing_ok=True)
                    downloaded.append(output_file)
                    if i == 0:
                        content.file_path = str(output_file)
                    logger.info(f"[Download] [{pair_label}] [OK] 已合并: {output_file.name}")
                    
                    # 更新进度
                    if progress_callback:
                        progress_callback((i + 1) / total)
                    if task_id:
                        from .download_queue import download_queue
                        download_queue.update_progress(task_id, (i + 1) / total)
                    
                    # 如果启用了 Apple Live Photo 转换
                    if apple_live_photo:
                        try:
                            from .motion_photo import create_apple_live_photo_from_motion_photo
                            apple_output_dir = output_dir / 'apple_live_photo'
                            jpeg_path, mov_path = create_apple_live_photo_from_motion_photo(
                                output_file, 
                                output_dir=apple_output_dir
                            )
                            downloaded.append(jpeg_path)
                            downloaded.append(mov_path)
                            logger.info(f"[Download] [{pair_label}] [OK] Apple Live Photo 已生成")
                        except Exception as e:
                            logger.info(f"[Download] [{pair_label}] Apple Live Photo 转换失败: {e}")
                    
                except Exception as e:
                    logger.info(f"[Download] [{pair_label}] 合并失败: {e}，保留原始文件")
                    downloaded.extend([img_path, vid_path])
        
        else:
            # 普通图文下载
            images_dir = get_download_subdir('images')
            base = build_download_base(content)
            for idx, img in enumerate(content.images):
                # 检查是否暂停/取消
                from .utils import check_download_status
                check_download_status(task_id)
                
                filepath = images_dir / f"{base}_{idx+1}.{img.file_ext}"
                
                # 已存在（含旧命名 douyin_<id>_N）且未指定覆盖 → 跳过
                if rename_strategy != "overwrite":
                    existing = _existing_target([
                        filepath,
                        images_dir / f"douyin_{content.item_id}_{idx+1}.{img.file_ext}",
                    ])
                    if existing:
                        logger.info(f"[Download] 已存在，跳过: {existing.name}")
                        downloaded.append(existing)
                        continue
                
                logger.info(f"[Download] 下载 {img.type} {idx+1}/{len(content.images)}: {filepath.name}")
                await download_file(client, img.url, filepath, task_id, rename_strategy=rename_strategy)
                downloaded.append(filepath)
                
                # 更新进度
                if progress_callback:
                    progress_callback((idx + 1) / len(content.images))
                if task_id:
                    from .download_queue import download_queue
                    download_queue.update_progress(task_id, (idx + 1) / len(content.images))
    
    return downloaded

async def fetch(input_text: str, output_dir: str | Path = "./downloads", merge_motion_photo: bool = True, apple_live_photo: bool = False) -> DouyinContent:
    """一站式解析下载"""
    content = await fetch_content(input_text)
    await download_content(content, output_dir, merge_motion_photo, apple_live_photo)
    return content


async def fetch_video_info(item_id: str) -> DouyinContent:
    url = f"https://www.douyin.com/video/{item_id}"
    return await fetch_content(url)


async def download_video(content: DouyinContent, output_dir: str | Path = "./downloads") -> Path:
    files = await download_content(content, output_dir)
    return files[0] if files else None




