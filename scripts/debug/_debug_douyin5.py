"""调试脚本：检查桌面版 douyin.com 页面数据结构"""
import asyncio
import re
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import httpx

async def main():
    url = "https://v.douyin.com/Z7oxG24Abio/"
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": ua, "Referer": "https://www.douyin.com/"})
        html = resp.text

    print(f"最终URL: {resp.url}")
    print(f"HTML长度: {len(html)}")

    # 搜索各种数据标记
    markers = [
        "window._ROUTER_DATA",
        "window.__INITIAL_STATE__",
        "window.__PRELOADED_STATE__",
        "RENDER_DATA",
        "_SSR_HYDRATED_DATA",
        "aweme_detail",
        "videoInfoRes",
        "item_list",
        "play_addr",
        "playAddr",
        "douyinvod",
    ]
    print("\n=== 页面标记搜索 ===")
    for m in markers:
        count = len(re.findall(re.escape(m), html))
        if count > 0:
            print(f"  {m}: 出现 {count} 次")

    # 检查各种 window.xxx = JSON 结构
    print("\n=== 尝试各种 JSON 提取 ===")

    # 1. _ROUTER_DATA
    match = re.search(r'window\._ROUTER_DATA\s*=\s*', html)
    if match:
        print(f"  找到 window._ROUTER_DATA, 位置 {match.start()}")
        from downloadkit.douyin import OptimizedOfficialParser
        parser = OptimizedOfficialParser()
        data = parser._extract_json(html, match.end())
        if data:
            if isinstance(data, dict):
                print(f"  顶层keys: {list(data.keys())[:15]}")
                ld = data.get("loaderData", data)
                print(f"  loaderData keys: {list(ld.keys())[:15]}")
                for k, v in list(ld.items())[:5]:
                    if isinstance(v, dict):
                        print(f"    {k}: dict({list(v.keys())[:10]})")
                    elif isinstance(v, list):
                        print(f"    {k}: list(len={len(v)})")
                    elif isinstance(v, str) and len(v) > 50:
                        print(f"    {k}: str({len(v)}) = {v[:150]}...")

    # 2. __INITIAL_STATE__ / __PRELOADED_STATE__
    for state_name in ["__INITIAL_STATE__", "__PRELOADED_STATE__"]:
        match = re.search(rf'window\.{state_name}\s*=\s*', html)
        if match:
            print(f"  找到 {state_name}, 位置 {match.start()}")
            from downloadkit.douyin import OptimizedOfficialParser
            parser = OptimizedOfficialParser()
            data = parser._extract_json(html, match.end())
            if data and isinstance(data, dict):
                print(f"  {state_name} keys: {list(data.keys())[:20]}")
                # 查找含视频信息的子字典
                def search_for_video(d, path="", depth=0):
                    if depth > 4:
                        return
                    if isinstance(d, dict):
                        for k, v in d.items():
                            np = f"{path}.{k}" if path else k
                            if k in ("video", "aweme_detail", "awemeInfo", "item_list"):
                                print(f"    找到 {np}: {type(v).__name__}")
                                if isinstance(v, dict):
                                    print(f"      内部keys: {list(v.keys())[:15]}")
                                elif isinstance(v, list) and len(v) > 0:
                                    print(f"      列表长度: {len(v)}")
                                    if isinstance(v[0], dict):
                                        print(f"      第一个元素keys: {list(v[0].keys())[:15]}")
                            elif isinstance(v, (dict, list)):
                                search_for_video(v, np, depth + 1)
                    elif isinstance(d, list):
                        for i, item in enumerate(d[:3]):
                            np = f"{path}[{i}]"
                            if isinstance(item, (dict, list)):
                                search_for_video(item, np, depth + 1)
                search_for_video(data)

    # 3. 暴力搜索 aweme_detail 及其周围数据
    print("\n=== 暴力搜索 aweme_detail ===")
    ad_matches = list(re.finditer(r'"aweme_detail"\s*:', html))
    print(f"  aweme_detail 出现 {len(ad_matches)} 次")
    if ad_matches:
        from downloadkit.douyin import OptimizedOfficialParser
        parser = OptimizedOfficialParser()
        for m in ad_matches[:3]:
            data = parser._extract_json(html, m.start())
            if data:
                if isinstance(data, dict):
                    ad = data.get("aweme_detail")
                    if ad and isinstance(ad, dict):
                        print(f"  找到aweme_detail! keys: {list(ad.keys())[:20]}")
                        v = ad.get("video")
                        if isinstance(v, dict):
                            print(f"    video keys: {list(v.keys())[:15]}")
                            for vk in ("play_addr", "play_addr_h264", "download_addr"):
                                if vk in v and isinstance(v[vk], dict):
                                    ul = v[vk].get("url_list", [])
                                    for u in ul[:2]:
                                        print(f"      {vk}: {u[:200]}")
                break

    # 4. 保存HTML以便人工检查
    outpath = Path(__file__).parent / "_douyin_page.html"
    outpath.write_text(html, encoding="utf-8")
    print(f"\n  已保存HTML到 {outpath}")

if __name__ == "__main__":
    asyncio.run(main())
