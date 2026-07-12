"""测试抖音 Cookie 加载和 story_25_filter 绕过"""
import sys; sys.path.insert(0, '.')
import asyncio
import httpx

async def main():
    # 1. 测试浏览器 Cookie 获取
    print("=== 1. 浏览器 Cookie 测试 ===")
    try:
        from downloadkit.browser_cookie import get_douyin_cookie
        cookies = get_douyin_cookie('edge')
        print(f"Edge: {len(cookies)} 个 .douyin.com cookie")
        for k, v in sorted(cookies.items()):
            mask = v[:15] + "..." if len(v) > 15 else v
            print(f"  {k} = {mask}")
        if 'sessionid' in cookies:
            print("✅ sessionid 存在 - 用户已登录")
        else:
            print("❌ sessionid 不存在 - 用户未登录")
    except Exception as e:
        print(f"Edge 获取失败: {e}")

    # 2. 测试 _load_user_cookies()
    print("\n=== 2. _load_user_cookies() 测试 ===")
    try:
        from downloadkit.douyin import _parser
        cookie_str = _parser._load_user_cookies()
        if cookie_str:
            print(f"返回: {len(cookie_str)} 字符")
            has_session = 'sessionid' in cookie_str
            print(f"  含 sessionid: {has_session}")
            print(f"  前80字符: {cookie_str[:80]}")
        else:
            print("返回: 空 (无用户 Cookie)")
    except Exception as e:
        print(f"异常: {e}")

    # 3. 测试带 Cookie 的 API 请求
    print("\n=== 3. 带 Cookie 的 API 请求 ===")
    item_id = '7650897530201434478'
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    ttwid = await _parser._get_ttwid(ua)
    user_cookie = _parser._load_user_cookies()
    if ttwid:
        base_cookie = f"ttwid={ttwid}"
        if user_cookie:
            if 'ttwid' not in user_cookie:
                base_cookie = f"ttwid={ttwid}; {user_cookie}"
            else:
                base_cookie = user_cookie
        print(f"Cookie (前80): {base_cookie[:80]}...")
        
        params = _parser._build_detail_params(item_id)
        url = "https://www.douyin.com/aweme/v1/web/aweme/detail/?"
        url += "&".join(f"{k}={v}" for k, v in params.items())
        signed = _parser._generate_x_bogus(url, ua)
        
        headers = {
            "User-Agent": ua,
            "Referer": "https://www.douyin.com/",
            "Cookie": base_cookie,
            "Accept": "application/json, text/plain, */*",
        }
        
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(signed, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                sc = data.get('status_code', -1)
                detail = data.get('aweme_detail') is not None
                fr = data.get('filter_detail', {}).get('filter_reason', 'none')
                print(f"status_code={sc} | detail={detail} | filter={fr}")
                if detail:
                    ad = data.get('aweme_detail', {})
                    print(f"✅ 绕过 story_25_filter 成功!")
                    print(f"   标题: {ad.get('desc', '')[:40]}")
                    print(f"   作者: {ad.get('author', {}).get('nickname', '')}")
                elif fr:
                    print(f"❌ story_25_filter 仍然生效 (当前Cookie无权限访问此日常作品)")
                else:
                    print(f"其他过滤: {data}")
            else:
                print(f"请求失败: 状态码={resp.status_code}")
    else:
        print("无法获取 ttwid，跳过 API 测试")

asyncio.run(main())
