import asyncio
import httpx

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

async def main():
    kw = "晴天"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        r = await c.get(f"https://www.gequbao.com/s/{kw}", headers=HEADERS)
        with open("probe_gequbao.html", "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"gequbao: status={r.status_code}, size={len(r.text)}")

        r = await c.post("https://music.itzo.cn/a.php",
                         data={"input": kw, "filter": "name", "type": "netease", "page": "1"},
                         headers=HEADERS)
        with open("probe_itzo.html", "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"itzo: status={r.status_code}, size={len(r.text)}")

asyncio.run(main())
