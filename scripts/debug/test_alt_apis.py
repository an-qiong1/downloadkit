"""测试替代 API 端点绕过 story_25_filter"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from httpx import AsyncClient

# 已知限制的视频
ITEM_ID = "7650897530201434478"

# 尝试不同 API 端点和参数组合
configs = [
    # 1. 无 /web/ 路径 (移动端风格)
    {"host": "www.douyin.com", "path": f"/aweme/v1/aweme/detail/", "desc": "mobile-style path", "extra": {"aweme_id": ITEM_ID, "version_code": "24.5.0"}, "use_bogus": True},
    
    # 2. api.douyin.com
    {"host": "api.douyin.com", "path": f"/aweme/v1/web/aweme/detail/", "desc": "api.douyin.com", "extra": {"aweme_id": ITEM_ID}, "use_bogus": True},
    
    # 3. aweme.snssdk.com (服务器 CDN)
    {"host": "aweme.snssdk.com", "path": f"/aweme/v1/web/aweme/detail/", "desc": "aweme.snssdk.com", "extra": {"aweme_id": ITEM_ID}, "use_bogus": True},
    
    # 4. 试试移动端参数
    {"host": "www.douyin.com", "path": f"/aweme/v1/aweme/detail/", "desc": "mobile + device_id", "extra": {"aweme_id": ITEM_ID, "device_platform": "android", "version_code": "270200", "device_type": "Pixel 7", "os_version": "14"}, "use_bogus": False},
    
    # 5. 尝试不带 version_code
    {"host": "www.douyin.com", "path": f"/aweme/v1/web/aweme/detail/", "desc": "no version code", "extra": {"aweme_id": ITEM_ID}, "use_bogus": True},
    
    # 6. 尝试用 feed 端点
    {"host": "www.douyin.com", "path": f"/aweme/v1/web/feed/", "desc": "feed endpoint", "extra": {"aweme_id": ITEM_ID}, "use_bogus": True},
    
    # 7. 尝试多数据端点
    {"host": "www.douyin.com", "path": f"/aweme/v1/multi/aweme/detail/", "desc": "multi detail", "extra": {"aweme_ids": f"[\"{ITEM_ID}\"]", "need_download": 1}, "use_bogus": True},
    
    # 8. 不同的 UA
    {"host": "www.douyin.com", "path": f"/aweme/v1/web/aweme/detail/", "desc": "mobile UA", "extra": {"aweme_id": ITEM_ID}, "use_bogus": True, "ua": "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.43 Mobile Safari/537.36"},
    
    # 9. douyin.com/video/ 页面直接请求
    {"host": "www.douyin.com", "path": f"/video/{ITEM_ID}", "desc": "direct video page", "extra": {}, "use_bogus": False, "raw": True},
    
    # 10. 尝试用 is_douyin=1
    {"host": "www.douyin.com", "path": f"/aweme/v1/web/aweme/detail/", "desc": "with is_douyin", "extra": {"aweme_id": ITEM_ID, "is_douyin": 1, "is_ios": 0}, "use_bogus": True},
]

async def try_request(cfg):
    is_raw = cfg.get("raw", False)
    path = cfg["path"]
    params = cfg.get("extra", {})
    
    ua = cfg.get("ua", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0")
    headers = {
        "User-Agent": ua,
        "Accept": "*/*",
        "Referer": "https://www.douyin.com/",
    }
    
    url = f"https://{cfg['host']}{path}"
    
    # 获取 ttwid
    from downloadkit.douyin import _get_ttwid
    ttwid = await _get_ttwid(aid=1768)
    
    async with AsyncClient(timeout=15, follow_redirects=False) as client:
        if cfg["use_bogus"]:
            # 添加 X-Bogus
            from downloadkit.a_bogus import XBogus
            import urllib.parse
            base_url = url
            if params:
                base_url = url + "?" + urllib.parse.urlencode(params)
            bogus = XBogus()
            signed_url = bogus.run(base_url, ua)
            if signed_url and "?" in signed_url:
                # 从 signed_url 提取 X-Bogus 和参数
                query = signed_url.split("?", 1)[1]
                from urllib.parse import parse_qs
                qs = parse_qs(query)
                for k, v in qs.items():
                    if len(v) == 1:
                        params[k] = v[0]
                    else:
                        params[k] = v
        
        try:
            if is_raw:
                resp = await client.get(url, headers=headers, params=params)
                # 直接页面请求检查是否有 _ROUTER_DATA
                if "_ROUTER_DATA" in resp.text:
                    print(f"✅ [{cfg['desc']}] 状态码={resp.status_code}, 有 _ROUTER_DATA")
                    # 检查是否包含视频信息
                    if "aweme_list" in resp.text or "item_list" in resp.text:
                        print(f"   👍 包含内容数据!")
                else:
                    print(f"❌ [{cfg['desc']}] 状态码={resp.status_code}, 无 _ROUTER_DATA")
            else:
                resp = await client.get(url, headers=headers, params=params)
                body = resp.text[:500]
                try:
                    data = resp.json()
                    keys = list(data.keys())
                    if "status_code" in data:
                        sc = data["status_code"]
                        if sc == 0:
                            if data.get("aweme_detail"):
                                print(f"✅ [{cfg['desc']}] 状态码=0, 有 aweme_detail! ✅")
                                # 显示视频信息
                                det = data["aweme_detail"]
                                print(f"   title: {det.get('desc', 'N/A')[:60]}")
                                if "video" in det:
                                    print(f"   有 video 数据! ✅")
                            elif data.get("filter_detail"):
                                fr = data["filter_detail"].get("filter_reason", "")
                                print(f"❌ [{cfg['desc']}] status_code=0, filter_detail.reason={fr}")
                            else:
                                print(f"⚠️ [{cfg['desc']}] status_code=0, keys={keys}")
                        else:
                            msg = data.get("status_msg", "")
                            print(f"⚠️ [{cfg['desc']}] status_code={sc}, msg={msg}")
                    else:
                        print(f"⚠️ [{cfg['desc']}] 响应 keys={keys}, 前200字: {body[:200]}")
                except json.JSONDecodeError:
                    print(f"❌ [{cfg['desc']}] 状态码={resp.status_code}, 非JSON: {body[:200]}")
        except Exception as e:
            print(f"❌ [{cfg['desc']}] 异常: {e}")

async def main():
    # 同时测试前几个
    for cfg in configs[:6]:
        await try_request(cfg)

if __name__ == "__main__":
    asyncio.run(main())
