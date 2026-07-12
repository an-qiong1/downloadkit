"""调试脚本：检查 item_list 结构"""
import asyncio
import re
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import httpx

async def main():
    url = "https://v.douyin.com/Z7oxG24Abio/"
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": ua, "Referer": "https://www.douyin.com/"})
        html = resp.text

    match = re.search(r'_ROUTER_DATA\s*=\s*', html)
    if not match:
        print("未找到_ROUTER_DATA")
        return

    from downloadkit.douyin import OptimizedOfficialParser
    parser = OptimizedOfficialParser()
    data = parser._extract_json(html, match.end())
    if not data:
        print("JSON解析失败")
        return

    loader_data = data.get("loaderData", data)
    page_data = loader_data.get("video_(id)/page")
    video_info_res = page_data.get("videoInfoRes")
    item_list = video_info_res.get("item_list", [])

    print(f"item_list 长度: {len(item_list)}")

    for i, item in enumerate(item_list):
        print(f"\n=== item[{i}] keys: {list(item.keys())[:30]} ===")

        # 查找视频URL
        def find_video_urls(d, path="", depth=0, max_depth=8):
            if depth > max_depth:
                return
            if isinstance(d, dict):
                for k, v in d.items():
                    new_path = f"{path}.{k}" if path else k
                    if isinstance(v, str) and ("v.douyin" in v or "douyinvod" in v or "aweme.snssdk" in v or "play" in v.lower() or "url_list" in k.lower()):
                        print(f"  可能视频URL: {new_path} = {v[:300]}")
                    elif isinstance(v, dict):
                        find_video_urls(v, new_path, depth + 1, max_depth)
                    elif isinstance(v, list):
                        find_video_urls(v, new_path, depth + 1, max_depth)
            elif isinstance(d, list):
                for i2, item in enumerate(d):
                    new_path = f"{path}[{i2}]"
                    find_video_urls(item, new_path, depth + 1, max_depth)

        find_video_urls(item)

        # 打印 desc/author
        for k in ("desc", "author", "aweme_id", "video", "text_extra"):
            if k in item:
                val = item[k]
                if isinstance(val, str):
                    print(f"  {k}: {val[:200]}")
                elif isinstance(val, dict):
                    print(f"  {k}: dict({list(val.keys())[:15]})")

        # 打印 video 字段详情
        if "video" in item and isinstance(item["video"], dict):
            video = item["video"]
            print(f"  video keys: {list(video.keys())[:30]}")
            for vk in ("play_addr", "play_addr_h264", "play_addr_bytevc_1", "download_addr", "cover", "dynamic_cover", "origin_cover"):
                if vk in video:
                    val = video[vk]
                    if isinstance(val, dict):
                        print(f"    {vk}: dict({list(val.keys())[:10]})")
                        if "url_list" in val:
                            for u in val["url_list"][:3]:
                                print(f"      -> {u[:200]}")
                    elif isinstance(val, list):
                        print(f"    {vk}: list(len={len(val)})")
                        for u in val[:3]:
                            if isinstance(u, str):
                                print(f"      -> {u[:200]}")

        # 打印完整JSON片段
        snippet = json.dumps(item, ensure_ascii=False, default=str)[:5000]
        print(f"\n  完整JSON片段(前5000字符):\n  {snippet}")

if __name__ == "__main__":
    asyncio.run(main())
