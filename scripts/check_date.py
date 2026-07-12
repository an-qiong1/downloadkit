import asyncio
import datetime

async def main():
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = 'https://www.douyin.com/note/7552379142260395291'
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(5000)
        
        info = await page.evaluate('''() => {
            const title = document.querySelector('title')?.textContent || '';
            const desc = document.querySelector('[class*="desc"], [class*="title"]')?.textContent || '';
            const timeEl = document.querySelector('time, [class*="time"], [class*="date"]');
            const timeText = timeEl?.textContent || timeEl?.getAttribute('datetime') || '';
            
            const scripts = document.querySelectorAll('script');
            let createTime = '';
            for (const s of scripts) {
                const match = s.textContent.match(/create_time["\\s:]+(\\d{10})/);
                if (match) {
                    createTime = match[1];
                    break;
                }
            }
            
            return { title, desc, timeText, createTime };
        }''')
        
        print(f'标题: {info.get("title", "")[:100]}')
        print(f'描述: {info.get("desc", "")[:100]}')
        print(f'时间文本: {info.get("timeText", "")}')
        
        if info.get('createTime'):
            ts = int(info['createTime'])
            dt = datetime.datetime.fromtimestamp(ts)
            print(f'创建时间: {dt.strftime("%Y-%m-%d %H:%M:%S")}')
        
        await browser.close()

asyncio.run(main())
