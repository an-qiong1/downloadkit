"""
批量获取抖音用户主页作品列表（使用Playwright获取Cookie）
"""

import asyncio
import json
from pathlib import Path
from typing import List, Dict


async def fetch_user_posts_with_playwright(
    user_url: str,
    max_scroll: int = 50
) -> tuple:
    """使用Playwright获取用户主页所有作品"""
    from playwright.async_api import async_playwright
    
    sec_user_id = user_url.split('/user/')[1].split('?')[0] if '/user/' in user_url else ''
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
        )
        page = await context.new_page()
        
        print(f"[浏览器] 访问用户主页: {user_url}")
        await page.goto(user_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        
        # 获取Cookie
        cookies = await context.cookies()
        cookie_dict = {c['name']: c['value'] for c in cookies if 'douyin' in c.get('domain', '')}
        print(f"[Cookie] 获取到 {len(cookie_dict)} 个Cookie")
        
        # 保存Cookie
        cookie_file = Path("douyin_cookies.json")
        cookie_file.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"[Cookie] 已保存到 {cookie_file}")
        
        # 滚动加载所有作品
        print(f"\n[加载] 开始滚动加载作品...")
        
        all_links = set()
        prev_count = 0
        no_new_count = 0
        
        for scroll in range(max_scroll):
            links = await page.evaluate('''() => {
                const items = document.querySelectorAll('a[href*="/video/"], a[href*="/note/"]');
                return Array.from(items).map(a => {
                    const href = a.href;
                    const match = href.match(/\\/(video|note)\\/(\\d+)/);
                    if (match) {
                        return { type: match[1], id: match[2], href: href };
                    }
                    return null;
                }).filter(Boolean);
            }''')
            
            for link in links:
                all_links.add(link['id'])
            
            current_count = len(all_links)
            print(f"[滚动 {scroll+1}] 当前: {current_count} 个作品")
            
            if current_count == prev_count:
                no_new_count += 1
                if no_new_count >= 3:
                    print("[完成] 连续3次无新作品，停止滚动")
                    break
            else:
                no_new_count = 0
            
            prev_count = current_count
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(2000)
        
        # 构建作品列表
        posts_info = [{'id': aweme_id, 'type': 'note', 'href': f'https://www.douyin.com/note/{aweme_id}'} for aweme_id in all_links]
        
        await browser.close()
        
        print(f"[完成] 获取到 {len(posts_info)} 个作品")
        return posts_info, cookie_dict


async def fetch_aweme_detail(aweme_id: str, cookies: Dict[str, str]) -> Dict:
    """获取单个作品详情"""
    import httpx
    
    url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
    params = {
        "aweme_id": aweme_id,
        "aid": "6383",
        "cookie_enabled": "true",
        "platform": "PC"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Referer": "https://www.douyin.com/",
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers, cookies=cookies, timeout=30)
        return response.json()


def is_motion_photo(aweme_detail: Dict) -> bool:
    """判断是否为实况照片"""
    images = aweme_detail.get('images', [])
    if not images:
        return False
    
    for img in images:
        if img.get('video'):
            return True
    
    if images and aweme_detail.get('video'):
        return True
    
    return False


async def main():
    user_url = "https://www.douyin.com/user/MS4wLjABAAAAWjt8mmZeUH_Ld7yruwVQ5jX71jwX_9bRIt6y-BxfU7k"
    
    posts, cookies = await fetch_user_posts_with_playwright(user_url)
    
    if not posts:
        print("[结束] 未获取到任何作品")
        return
    
    print(f"\n[筛选] 开始判断作品类型...")
    motion_photos = []
    
    for i, post in enumerate(posts[:30]):  # 先测试前30个
        aweme_id = post['id']
        print(f"[{i+1}/{min(len(posts), 30)}] 检查 {aweme_id}...", end=" ")
        
        try:
            detail = await fetch_aweme_detail(aweme_id, cookies)
            aweme_data = detail.get('aweme_detail', {})
            
            if is_motion_photo(aweme_data):
                motion_photos.append({
                    'aweme_id': aweme_id,
                    'desc': aweme_data.get('desc', ''),
                    'url': f"https://www.douyin.com/note/{aweme_id}"
                })
                print(f"实况照片 ✓")
            else:
                print(f"普通作品")
        except Exception as e:
            print(f"获取失败: {e}")
        
        await asyncio.sleep(0.5)
    
    output_file = Path("downloads") / "motion_photos.json"
    output_file.parent.mkdir(exist_ok=True)
    
    result = {
        "user_url": user_url,
        "total_posts": len(posts),
        "checked": min(len(posts), 30),
        "motion_photos_count": len(motion_photos),
        "motion_photos": motion_photos
    }
    
    output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n[保存] 结果已保存到: {output_file}")
    
    if motion_photos:
        print(f"\n{'='*60}")
        print(f"发现 {len(motion_photos)} 个实况照片:")
        print(f"{'='*60}")
        for i, mp in enumerate(motion_photos, 1):
            print(f"{i}. {mp['desc'][:60]}")
            print(f"   链接: {mp['url']}")
    else:
        print("\n[结果] 未发现实况照片")


if __name__ == "__main__":
    asyncio.run(main())
