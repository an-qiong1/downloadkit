"""
douyin_browser 集成测试：真实浏览器
需要已登录的 profile，或可导入 cookie
"""
import asyncio
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from downloadkit.douyin_browser import (
    DouyinBrowser,
    DouyinLoginRequired,
)

CREATORS = [
    ("笔吧评测室", "MS4wLjABAAAA9jVXMI9P5Gye45GdF88OIr1Frk2Gf1q7PS416m3PxGo"),
    ("极客湾Geekerwan", "MS4wLjABAAAAXXVrVvbTDOhdGW_LzlSDkdN2hZT_CRXmzzafGN-GIbkV6skPAaH2uANSFru076ZT"),
]

TEST_VIDEO = "7689023840848006451"
OUT = Path("test_downloads")

COOKIE_SRC = Path(r"C:\我的仓库\工作空间\temp\downloadkit-f2-test\edge_cookies.txt")


async def main():
    profile = Path("test_browser_profile")

    # 复用之前验证过的 profile（含登录态）
    src = Path(r"C:\我的仓库\工作空间\temp\downloadkit-f2-test\pw_profile")
    if src.exists() and not profile.exists():
        print(f"复制已登录 profile: {src} -> {profile}")
        shutil.copytree(src, profile)
    profile.mkdir(parents=True, exist_ok=True)

    async with DouyinBrowser(headless=True, profile_dir=profile) as dy:
        # 1. 登录态
        print("=" * 62)
        print("测试 1: 登录态")
        print("=" * 62)
        logged = await dy.is_logged_in()
        print(f"  已登录: {logged}")

        if not logged and COOKIE_SRC.exists():
            print(f"  从 {COOKIE_SRC.name} 导入 cookie...")
            n = await dy.import_cookies(COOKIE_SRC)
            print(f"  导入 {n} 条，重新检查")
            logged = await dy.is_logged_in()
            print(f"  已登录: {logged}")

        if not logged:
            print("\n>>> 无登录态，后续测试可能失败")
            return 1

        # 2. 创作者主页
        print()
        print("=" * 62)
        print("测试 2: 创作者主页作品列表")
        print("=" * 62)
        t0 = time.time()
        results = []
        for expect_name, sec in CREATORS:
            try:
                c = await dy.fetch_creator(sec, max_scrolls=4)
                print(f"  [OK] {expect_name}")
                print(f"       实际昵称: {c.nickname}")
                print(f"       作品数: {len(c.video_ids)}")
                print(f"       最新3个: {c.video_ids[:3]}")
                results.append(c)
            except Exception as e:
                print(f"  [FAIL] {expect_name}: {type(e).__name__}: {str(e)[:120]}")
        print(f"  耗时 {time.time() - t0:.1f}s")

        if not results:
            return 1

        # 3. 视频解析
        print()
        print("=" * 62)
        print("测试 3: 视频流解析")
        print("=" * 62)
        t0 = time.time()
        try:
            item = await dy.resolve_stream(TEST_VIDEO)
            print(f"  [OK] {item.aweme_id}")
            print(f"       标题: {item.title[:50]}")
            print(f"       作者: {item.author}")
            print(f"       大小: {item.size:,} bytes")
            print(f"       流地址: {item.stream_url[:80]}...")
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {str(e)[:150]}")
            return 1
        print(f"  耗时 {time.time() - t0:.1f}s")

        # 4. 下载 + 进度回调
        print()
        print("=" * 62)
        print("测试 4: 完整下载 + 进度回调")
        print("=" * 62)
        last = {"pct": 0}

        def on_progress(done, total):
            pct = int(done / total * 100)
            if pct >= last["pct"] + 20:
                last["pct"] = pct
                print(f"    {pct:>3}%  {done:,}/{total:,}")

        OUT.mkdir(exist_ok=True)
        t0 = time.time()
        try:
            path = await dy.download(TEST_VIDEO, OUT, progress_callback=on_progress)
            elapsed = time.time() - t0
            size = path.stat().st_size
            print(f"\n  [OK] {path}")
            print(f"       {size:,} bytes  用时 {elapsed:.1f}s  "
                  f"速度 {size/1024/1024/max(elapsed,0.1):.2f} MB/s")

            # ffprobe 验证
            import subprocess
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=format_name,duration", "-of", "default=nw=1", str(path)],
                capture_output=True, text=True, timeout=60)
            print(f"       ffprobe: {r.stdout.strip() or r.stderr.strip()[:100]}")

            if size > 1_000_000 and "mp4" in r.stdout:
                print("\n>>> 全部测试通过")
                return 0
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {str(e)[:200]}")
            return 1

    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
