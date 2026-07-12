"""Test different Douyin API endpoints for story_25_filter bypass."""
import asyncio, sys; sys.path.insert(0, '.')
import httpx
from downloadkit.douyin import _parser

async def main():
    item_id = '7650897530201434478'
    desktop_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    ttwid = await _parser._get_ttwid(desktop_ua)
    ttwid_preview = ttwid[:40] if ttwid else "none"
    print(f'ttwid: {ttwid_preview}')

    headers = {
        'User-Agent': desktop_ua,
        'Referer': 'https://www.douyin.com/',
        'Cookie': f'ttwid={ttwid}' if ttwid else '',
        'Accept': 'application/json, text/plain, */*',
    }

    endpoints = [
        ('web-6383', f'https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&aweme_id={item_id}&pc_client_type=1&channel=channel_pc_web'),
        ('web-no-prefix', f'https://www.douyin.com/aweme/v1/aweme/detail/?aweme_id={item_id}&aid=6383'),
        ('snssdk-ios', f'https://aweme.snssdk.com/aweme/v1/aweme/detail/?aweme_id={item_id}&aid=1128&device_platform=ios'),
        ('iesdouyin', f'https://www.iesdouyin.com/aweme/v1/aweme/detail/?aweme_id={item_id}&aid=1128'),
        ('mdouyin', f'https://m.douyin.com/aweme/v1/aweme/detail/?aweme_id={item_id}&aid=1128'),
        ('web-full', f'https://www.douyin.com/aweme/v1/aweme/detail/?device_platform=webapp&aid=6383&aweme_id={item_id}'),
        ('tiktokv', f'https://api.tiktokv.com/aweme/v1/aweme/detail/?aweme_id={item_id}'),
        ('douyin-note', f'https://www.douyin.com/aweme/v1/web/note/detail/?device_platform=webapp&aid=6383&note_id={item_id}'),
    ]

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for name, url in endpoints:
            for xb_label, final_url in [('noxb', url), ('xbog', _parser._generate_x_bogus(url, desktop_ua))]:
                try:
                    resp = await client.get(final_url, headers=headers)
                    content_type = resp.headers.get('content-type', '')
                    if resp.status_code == 200 and ('json' in content_type or resp.text.startswith('{')):
                        try:
                            data = resp.json()
                        except Exception:
                            print(f'{name:15s} | {xb_label:4s} | 200 bad-json | {resp.text[:60]}')
                            continue
                        sc = data.get('status_code', -1)
                        has_ad = data.get('aweme_detail') is not None
                        fr = data.get('filter_detail', {}).get('filter_reason', 'none')
                        msg = data.get('status_msg', '')
                        print(f'{name:15s} | {xb_label:4s} | sc={sc} | detail={has_ad} | filter={fr} | msg={msg[:40]}')
                    elif resp.status_code == 302:
                        loc = resp.headers.get('location', '')[:60]
                        print(f'{name:15s} | {xb_label:4s} | 302 -> {loc}')
                    else:
                        print(f'{name:15s} | {xb_label:4s} | {resp.status_code} | {content_type[:30]} | {resp.text[:60]}')
                except Exception as e:
                    print(f'{name:15s} | {xb_label:4s} | ERROR: {e}')

asyncio.run(main())
