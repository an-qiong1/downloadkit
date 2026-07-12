"""
影视资源聚合搜索模块
支持多个CMS采集站API，提供搜索、详情、分类、剧集解析功能

支持的资源站：
- 暴风资源、量子资源、光速资源、非凡资源、红牛资源
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

import httpx
import logging

logger = logging.getLogger(__name__)


@dataclass
class MovieInfo:
    """影视信息数据结构"""
    vod_id: str = ""           # 视频ID
    vod_name: str = ""         # 视频名称
    vod_pic: str = ""          # 封面图片URL
    vod_year: str = ""         # 年份
    vod_area: str = ""         # 地区
    vod_class: str = ""        # 类型标签
    vod_actor: str = ""        # 演员
    vod_director: str = ""     # 导演
    vod_content: str = ""      # 简介
    vod_play_from: str = ""    # 播放源名称
    vod_play_url: str = ""     # 播放地址（格式：第1集$url1#第2集$url2）
    type_name: str = ""        # 分类名称（电影/电视剧/动漫/综艺）


@dataclass
class Episode:
    """剧集信息"""
    name: str = ""             # 剧集名称（如：第1集、HD、TC等）
    url: str = ""              # 播放地址
    play_from: str = ""        # 播放源名称


@dataclass
class PlaySource:
    """播放源信息"""
    name: str = ""             # 播放源名称
    episodes: List[Episode] = field(default_factory=list)


class MovieSource:
    """影视资源聚合搜索类"""
    
    # CMS采集站API地址
    SOURCES: Dict[str, str] = {
        "暴风资源": "https://bfzyapi.com/api.php/provide/vod/",
        "量子资源": "https://cj.lziapi.com/api.php/provide/vod/",
        "光速资源": "https://api.guangsuapi.com/api.php/provide/vod/",
        "非凡资源": "https://cj.ffzyapi.com/api.php/provide/vod/",
        "红牛资源": "https://www.hongniuzy2.com/api.php/provide/vod/",
    }
    
    # 默认请求头
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    
    # 超时时间（秒）
    TIMEOUT = 15
    
    def get_sources(self) -> List[str]:
        """返回所有可用源名称"""
        return list(self.SOURCES.keys())
    
    async def search(self, keyword: str, source: str = None) -> List[MovieInfo]:
        """
        搜索影视资源
        
        Args:
            keyword: 搜索关键词
            source: 指定资源站名称，为None时尝试所有源
            
        Returns:
            影视信息列表
        """
        if source:
            if source not in self.SOURCES:
                logger.error(f"未知的资源站: {source}")
                return []
            return await self._search_single(keyword, source)
        
        # 尝试所有源，返回第一个成功的结果
        return await self._fetch_with_fallback(
            lambda src: self._search_single(keyword, src)
        )
    
    async def get_detail(self, vod_id: str, source: str = None) -> Optional[MovieInfo]:
        """
        获取影视详情
        
        Args:
            vod_id: 视频ID
            source: 指定资源站名称，为None时尝试所有源
            
        Returns:
            影视详细信息，失败返回None
        """
        if source:
            if source not in self.SOURCES:
                logger.error(f"未知的资源站: {source}")
                return None
            return await self._get_detail_single(vod_id, source)
        
        # 尝试所有源
        for src_name in self.SOURCES:
            try:
                result = await self._get_detail_single(vod_id, src_name)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"从 {src_name} 获取详情失败: {e}")
                continue
        
        return None
    
    async def get_category(self, category: str = "", page: int = 1, source: str = None) -> List[MovieInfo]:
        """
        获取分类列表
        
        Args:
            category: 分类名称或ID（如：电影、电视剧、动漫、综艺，或数字ID）
            page: 页码
            source: 指定资源站名称，为None时使用第一个源
            
        Returns:
            影视信息列表
        """
        # 分类名称到ID的映射（不同站点可能不同，这里使用常见映射）
        category_map = {
            "电影": "1",
            "电视剧": "2",
            "动漫": "3",
            "综艺": "4",
            "纪录片": "5",
        }
        
        category_id = category_map.get(category, category)
        
        if source:
            if source not in self.SOURCES:
                logger.error(f"未知的资源站: {source}")
                return []
            return await self._get_category_single(category_id, page, source)
        
        # 默认使用第一个可用源
        for src_name in self.SOURCES:
            try:
                result = await self._get_category_single(category_id, page, src_name)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"从 {src_name} 获取分类失败: {e}")
                continue
        
        return []
    
    def parse_episodes(self, play_url: str) -> List[PlaySource]:
        """
        解析剧集列表
        
        播放地址格式：
        - 多个播放源用 $$$ 分隔
        - 每个播放源内，剧集用 # 分隔
        - 每个剧集格式为：名称$url
        
        Args:
            play_url: 播放地址字符串
            
        Returns:
            播放源列表，每个播放源包含剧集列表
        """
        if not play_url:
            return []
        
        sources = []
        
        # 按 $$$ 分隔不同播放源
        source_parts = play_url.split("$$$")
        
        for source_part in source_parts:
            if not source_part.strip():
                continue
            
            play_source = PlaySource()
            
            # 按 # 分隔不同剧集
            episode_parts = source_part.split("#")
            
            for ep_part in episode_parts:
                if not ep_part.strip():
                    continue
                
                # 按 $ 分隔名称和URL
                if "$" in ep_part:
                    name, url = ep_part.split("$", 1)
                    episode = Episode(
                        name=name.strip(),
                        url=url.strip(),
                        play_from=play_source.name
                    )
                    play_source.episodes.append(episode)
            
            if play_source.episodes:
                # 尝试从第一个剧集推断播放源名称
                sources.append(play_source)
        
        return sources
    
    async def _search_single(self, keyword: str, source: str) -> List[MovieInfo]:
        """从单个资源站搜索"""
        api_url = self.SOURCES[source]
        params = {
            "ac": "detail",
            "wd": keyword,
        }
        
        data = await self._request(api_url, params)
        if not data:
            return []
        
        return self._parse_vod_list(data, source)
    
    async def _get_detail_single(self, vod_id: str, source: str) -> Optional[MovieInfo]:
        """从单个资源站获取详情"""
        api_url = self.SOURCES[source]
        params = {
            "ac": "detail",
            "ids": vod_id,
        }
        
        data = await self._request(api_url, params)
        if not data:
            return None
        
        vod_list = data.get("list", [])
        if not vod_list:
            return None
        
        return self._parse_vod_info(vod_list[0], source)
    
    async def _get_category_single(self, category: str, page: int, source: str) -> List[MovieInfo]:
        """从单个资源站获取分类列表"""
        api_url = self.SOURCES[source]
        params = {
            "ac": "detail",
            "t": category,
            "pg": page,
        }
        
        data = await self._request(api_url, params)
        if not data:
            return []
        
        return self._parse_vod_list(data, source)
    
    async def _request(self, url: str, params: dict = None) -> Optional[dict]:
        """发送HTTP请求"""
        try:
            async with httpx.AsyncClient(
                timeout=self.TIMEOUT,
                follow_redirects=True,
                headers=self.HEADERS
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                
                data = response.json()
                
                # 检查API响应状态
                if data.get("code") == 1 or data.get("msg") == "success":
                    return data
                elif "list" in data:
                    # 有些API不返回code，直接返回数据
                    return data
                else:
                    logger.warning(f"API响应异常: {data.get('msg', '未知错误')}")
                    return data  # 仍然返回数据，让调用者处理
                    
        except httpx.TimeoutException:
            logger.error(f"请求超时: {url}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP错误 {e.response.status_code}: {url}")
            return None
        except Exception as e:
            logger.error(f"请求失败: {url} - {e}")
            return None
    
    def _parse_vod_list(self, data: dict, source: str) -> List[MovieInfo]:
        """解析视频列表"""
        vod_list = data.get("list", [])
        result = []
        
        for vod_data in vod_list:
            movie_info = self._parse_vod_info(vod_data, source)
            if movie_info:
                result.append(movie_info)
        
        return result
    
    def _parse_vod_info(self, vod_data: dict, source: str) -> Optional[MovieInfo]:
        """解析单个视频信息"""
        try:
            # 处理播放地址：添加源名称
            play_from = vod_data.get("vod_play_from", "")
            play_url = vod_data.get("vod_play_url", "")
            
            # 如果有多个播放源，为每个源添加名称
            if play_from and "$$$" in play_url:
                from_parts = play_from.split("$$$")
                url_parts = play_url.split("$$$")
                
                # 确保名称和URL数量匹配
                if len(from_parts) == len(url_parts):
                    # 保持原样，解析时会处理
                    pass
            
            return MovieInfo(
                vod_id=str(vod_data.get("vod_id", "")),
                vod_name=vod_data.get("vod_name", ""),
                vod_pic=vod_data.get("vod_pic", ""),
                vod_year=vod_data.get("vod_year", ""),
                vod_area=vod_data.get("vod_area", ""),
                vod_class=vod_data.get("vod_class", ""),
                vod_actor=vod_data.get("vod_actor", ""),
                vod_director=vod_data.get("vod_director", ""),
                vod_content=self._clean_html(vod_data.get("vod_content", "")),
                vod_play_from=play_from,
                vod_play_url=play_url,
                type_name=vod_data.get("type_name", ""),
            )
        except Exception as e:
            logger.error(f"解析视频信息失败: {e}")
            return None
    
    def _clean_html(self, text: str) -> str:
        """清理HTML标签"""
        if not text:
            return ""
        
        import re
        # 移除HTML标签
        clean_text = re.sub(r'<[^>]+>', '', text)
        # 移除多余空白
        clean_text = re.sub(r'\s+', ' ', clean_text)
        # 处理HTML实体
        clean_text = clean_text.replace('&nbsp;', ' ')
        clean_text = clean_text.replace('&lt;', '<')
        clean_text = clean_text.replace('&gt;', '>')
        clean_text = clean_text.replace('&amp;', '&')
        clean_text = clean_text.replace('&quot;', '"')
        
        return clean_text.strip()
    
    async def _fetch_with_fallback(self, fetch_func) -> List[MovieInfo]:
        """
        带回退的请求方法
        当一个源失败时自动尝试下一个源
        """
        errors = []
        
        for source_name in self.SOURCES:
            try:
                result = await fetch_func(source_name)
                if result:
                    return result
            except Exception as e:
                errors.append(f"{source_name}: {e}")
                logger.debug(f"源 {source_name} 失败: {e}")
                continue
        
        if errors:
            logger.warning(f"所有源都失败: {'; '.join(errors)}")
        
        return []


# 便捷函数
_movie_source = MovieSource()


async def search_movie(keyword: str, source: str = None) -> List[MovieInfo]:
    """搜索影视资源"""
    return await _movie_source.search(keyword, source)


async def get_movie_detail(vod_id: str, source: str = None) -> Optional[MovieInfo]:
    """获取影视详情"""
    return await _movie_source.get_detail(vod_id, source)


async def get_movie_category(category: str = "", page: int = 1, source: str = None) -> List[MovieInfo]:
    """获取分类列表"""
    return await _movie_source.get_category(category, page, source)


def get_available_sources() -> List[str]:
    """获取可用资源站列表"""
    return _movie_source.get_sources()


def parse_play_episodes(play_url: str) -> List[PlaySource]:
    """解析播放地址为剧集列表"""
    return _movie_source.parse_episodes(play_url)


# 测试代码
if __name__ == "__main__":
    async def test():
        source = MovieSource()
        
        print("=== 可用资源站 ===")
        print(source.get_sources())
        
        print("\n=== 搜索测试 ===")
        results = await source.search("三体")
        for movie in results[:3]:
            print(f"[{movie.type_name}] {movie.vod_name} ({movie.vod_year})")
            print(f"  演员: {movie.vod_actor[:50]}...")
            print(f"  来源: {movie.vod_play_from}")
            
            # 解析剧集
            if movie.vod_play_url:
                play_sources = source.parse_episodes(movie.vod_play_url)
                for ps in play_sources[:1]:  # 只显示第一个播放源
                    print(f"  剧集数: {len(ps.episodes)}")
                    for ep in ps.episodes[:3]:
                        print(f"    - {ep.name}: {ep.url[:50]}...")
            print()
    
    asyncio.run(test())
