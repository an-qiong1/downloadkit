"""调试脚本：获取抖音页面HTML并检查_ROUTER_DATA结构"""
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

    print("=== 跟随重定向获取落地页 ===")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": ua, "Referer": "https://www.douyin.com/"})
        print(f"最终URL: {resp.url}")
        html = resp.text

    print(f"\nHTML长度: {len(html)}")

    # 查找_ROUTER_DATA
    match = re.search(r'window\._ROUTER_DATA\s*=\s*', html)
    if not match:
        match = re.search(r'_ROUTER_DATA\s*=\s*', html)

    if match:
        print("\n=== 找到 _ROUTER_DATA ===")
        start = match.end()

        # 提取JSON
        from downloadkit.douyin import OptimizedOfficialParser
        parser = OptimizedOfficialParser()
        data = parser._extract_json(html, start)

        if data:
            loader_data = data.get("loaderData", data)
            print(f"loaderData keys: {list(loader_data.keys())[:20]}")

            # 检查每个 key 的结构
            for key in loader_data:
                print(f"\n--- key: {key} ---")
                val = loader_data[key]
                if isinstance(val, dict):
                    print(f"  子keys: {list(val.keys())[:20]}")
                    # 递归查找 aweme_detail 或 video相关
                    def find_aweme(d, depth=0, path=""):
                        if depth > 5:
                            return
                        if isinstance(d, dict):
                            for k, v in d.items():
                                new_path = f"{path}.{k}" if path else k
                                if k in ("aweme_detail", "awemeInfo", "video", "play_addr", "playAddr"):
                                    print(f"  找到: {new_path} -> {type(v).__name__}")
                                    if isinstance(v, dict):
                                        print(f"    内部keys: {list(v.keys())[:15]}")
                                elif isinstance(v, (dict, list)):
                                    find_aweme(v, depth + 1, new_path)
                        elif isinstance(d, list):
                            for i, item in enumerate(d[:3]):
                                find_aweme(item, depth + 1, f"{path}[{i}]")

                    find_aweme(val)
                    # 也打印 JSON snippet
                    snippet = json.dumps(val, ensure_ascii=False, default=str)[:2000]
                    print(f"\n  JSON片段 (前2000字符):\n  {snippet}")
                else:
                    print(f"  类型: {type(val).__name__}")
    else:
        print("未找到 _ROUTER_DATA")

if __name__ == "__main__":
    asyncio.run(main())
