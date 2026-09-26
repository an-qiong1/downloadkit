"""
douyin.py 改造后的端到端测试
验证：server.py / cli.py 走的公开 API 是否能通过浏览器后端正常工作
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

from downloadkit import douyin as dy

TEST_VIDEO = "7689023840848006451"
TEST_URL = f"https://www.douyin.com/video/{TEST_VIDEO}"
OUT = Path("test_dy_out")

COOKIE_SRC = Path(r"C:\我的仓库\工作空间\temp\downloadkit-f2-test\edge_cookies.txt")
SRC_PROFILE = Path(r"C:\我的仓库\工作空间\temp\downloadkit-f2-test\pw_profile")


async def main():
    OUT.mkdir(exist_ok=True)

    from downloadkit.douyin_browser import DouyinBrowser
    from downloadkit.utils import save_config

    # 下载目录指向测试目录
    save_config({"general": {
        "download_dir": str(OUT.resolve()),
        "download_dir_video": str((OUT / "videos").resolve()),
    }})

    # 注入已登录的浏览器实例
    dy._browser_instance = DouyinBrowser(headless=True, profile_dir=SRC_PROFILE)
    await dy._browser_instance.start()

    if not await dy._browser_instance.is_logged_in() and COOKIE_SRC.exists():
        n = await dy._browser_instance.import_cookies(COOKIE_SRC)
        print(f"导入 {n} 条 cookie")

    print("=" * 66)
    print("测试 1: parse_url / fetch_content（server 用的入口）")
    print("=" * 66)
    try:
        url = dy.parse_url(TEST_URL)
        print(f"  parse_url    -> {url}")

        content = await dy.fetch_content(TEST_URL)
        print(f"  content_type : {content.content_type}")
        print(f"  item_id      : {content.item_id}")
        print(f"  title        : {content.title[:50]}")
        print(f"  author       : {content.author}")
        print(f"  video_url    : {content.video_url[:70]}...")
        print(f"  浏览器后端   : {dy._is_browser_backend(content)}")
        print(f"  调试后端     : {dy._last_parse_result.get('backend')}")

        assert content.item_id == TEST_VIDEO, "item_id 不匹配"
        assert dy._is_browser_backend(content), "未走浏览器后端"
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {str(e)[:200]}")
        await dy.close_browser()
        return 1

    print()
    print("=" * 66)
    print("测试 2: download_content（应自动走浏览器下载）")
    print("=" * 66)
    seen = {"n": 0}

    def on_prog(p):
        seen["n"] += 1
        if seen["n"] % 5 == 0:
            print(f"    进度 {p * 100:.0f}%")

    try:
        paths = await dy.download_content(content, OUT, progress_callback=on_prog)
        print(f"  返回 {len(paths)} 个文件")
        for p in paths:
            print(f"    {p.name}  {p.stat().st_size:,} bytes")

        import subprocess
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
             "-of", "default=nw=1", str(paths[0])],
            capture_output=True, text=True, timeout=60)
        print(f"  ffprobe: {r.stdout.strip()[:120]}")

        if paths[0].stat().st_size > 5_000_000 and "822" in r.stdout:
            print("\n>>> 完整链路通过")
            await dy.close_browser()
            return 0
        print("\n>>> 文件不完整")
        await dy.close_browser()
        return 1
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {str(e)[:200]}")
        await dy.close_browser()
        return 1


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    finally:
        dy._browser_instance = None
    sys.exit(code)
