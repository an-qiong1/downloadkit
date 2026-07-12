"""调试脚本：尝试不同UA / 不同访问方式"""
import asyncio
import re
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import httpx

async def try_ua(name, ua, url):
    print(f"\n===== 尝试: {name} =====")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": ua,
            "Referer": "https://www.douyin.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        html = resp.text
        print(f"  最终URL: {resp.url}")
        print(f"  HTML长度: {len(html)}")

        from downloadkit.douyin import OptimizedOfficialParser
        parser = OptimizedOfficialParser()

        # 检查_ROUTER_DATA
        match = re.search(r'_ROUTER_DATA\s*=\s*', html)
        if match:
            data = parser._extract_json(html, match.end())
            if data:
                loader_data = data.get("loaderData", data)
                print(f"  loaderData keys: {list(loader_data.keys())[:15]}")
                page_data = loader_data.get("video_(id)/page")
                if page_data:
                    video_info_res = page_data.get("videoInfoRes")
                    if isinstance(video_info_res, dict):
                        item_list = video_info_res.get("item_list", [])
                        print(f"  item_list 长度: {len(item_list)}")
                        if item_list and isinstance(item_list[0], dict):
                            it = item_list[0]
                            print(f"  item keys: {list(it.keys())[:20]}")
                            if "video" in it and isinstance(it["video"], dict):
                                v = it["video"]
                                print(f"  video keys: {list(v.keys())[:20]}")
                                for vk in ("play_addr", "play_addr_h264", "download_addr"):
                                    if vk in v:
                                        val = v[vk]
                                        if isinstance(val, dict) and "url_list" in val:
                                            for u in val["url_list"][:2]:
                                                print(f"    {vk}: {u[:200]}")
                        return True
        # 检查其他格式
        for marker_name, marker_re in [
            ("__INITIAL_STATE__", r'window\.__INITIAL_STATE__\s*=\s*'),
            ("__PRELOADED_STATE__", r'window\.__PRELOADED_STATE__\s*=\s*'),
            ("RENDER_DATA", r'RENDER_DATA'),
        ]:
            if re.search(marker_re, html):
                print(f"  找到 {marker_name}")
        return False

async def main():
    url = "https://v.douyin.com/Z7oxG24Abio/"

    uas = [
        ("Chrome 桌面 (Windows)", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
        ("Chrome 桌面 (Mac)", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
        ("iPhone Safari", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"),
        ("Android Chrome", "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"),
        ("Douyin App WebView", "Mozilla/5.0 (Linux; Android 10; MI 9) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/91.0.4472.114 Mobile Safari/537.36 aweme_310501 JsSdk/2.0 NetType/WIFI Channel/xmstore"),
    ]

    for name, ua in uas:
        try:
            await try_ua(name, ua, url)
        except Exception as e:
            print(f"  出错: {e}")

if __name__ == "__main__":
    asyncio.run(main())
