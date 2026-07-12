"""调试脚本：深入检查 videoInfoRes 结构"""
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
    if not page_data:
        print("未找到 video_(id)/page")
        return

    video_info_res = page_data.get("videoInfoRes")
    print(f"videoInfoRes 类型: {type(video_info_res).__name__}")

    if isinstance(video_info_res, str):
        print(f"videoInfoRes 是字符串，尝试JSON解析...")
        try:
            video_info_res = json.loads(video_info_res)
        except Exception as e:
            print(f"  JSON解析失败: {e}")
            print(f"  字符串片段: {video_info_res[:500]}")

    if isinstance(video_info_res, dict):
        print(f"videoInfoRes keys: {list(video_info_res.keys())[:30]}")

        # 深度打印
        def deep_print(d, prefix="", depth=0, max_depth=6):
            if depth > max_depth:
                return
            if isinstance(d, dict):
                for k, v in d.items():
                    path = f"{prefix}.{k}" if prefix else k
                    if isinstance(v, str) and len(v) > 200:
                        print(f"  {path}: str({len(v)}) = {v[:200]}...")
                    elif isinstance(v, (dict, list)):
                        print(f"  {path}: {type(v).__name__}")
                        deep_print(v, path, depth + 1, max_depth)
                    else:
                        print(f"  {path}: {repr(v)[:200]}")
            elif isinstance(d, list):
                for i, item in enumerate(d[:5]):
                    path = f"{prefix}[{i}]"
                    if isinstance(item, (dict, list)):
                        print(f"  {path}: {type(item).__name__}")
                        deep_print(item, path, depth + 1, max_depth)
                    else:
                        print(f"  {path}: {repr(item)[:200]}")

        deep_print(video_info_res, "", 0, 6)

    # 同时也搜索 page_data 中的其他关键字段
    print("\n=== page_data 中其他有趣字段 ===")
    for key in page_data:
        if key not in ("ua", "isSpider", "webId", "query", "renderInSSR", "lastPath", "appName", "host", "isNotSupportWebp", "commonContext"):
            val = page_data[key]
            if isinstance(val, str) and len(val) > 100:
                print(f"  {key}: str({len(val)}) = {val[:300]}...")
            elif isinstance(val, dict):
                print(f"  {key}: dict({list(val.keys())[:10]})")
            elif isinstance(val, list):
                print(f"  {key}: list(len={len(val)})")
            else:
                print(f"  {key}: {repr(val)[:200]}")

if __name__ == "__main__":
    asyncio.run(main())
