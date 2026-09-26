"""
验证 server.py 与 cli.py 两条真实入口
"""
import asyncio
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"


async def wait_ready(timeout=90):
    import httpx
    t0 = time.time()
    async with httpx.AsyncClient(timeout=5) as c:
        while time.time() - t0 < timeout:
            try:
                r = await c.get(f"{BASE}/api/settings/get")
                if r.status_code == 200:
                    return time.time() - t0
            except Exception:
                pass
            await asyncio.sleep(1)
    return None


async def main():
    print("=" * 62)
    print("测试 A: server.py 启动（含浏览器预热）")
    print("=" * 62)

    env = {"PYTHONIOENCODING": "utf-8"}
    import os
    e = dict(os.environ)
    e.update(env)

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "info"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=e,
    )

    try:
        ready = await wait_ready()
        if ready is None:
            print("  [FAIL] server 未在 90 秒内就绪")
            proc.terminate()
            return 1
        print(f"  [OK] server 就绪，用时 {ready:.1f}s")

        # 检查关键接口
        import httpx
        async with httpx.AsyncClient(timeout=15) as c:
            for path, method, body in [
                ("/api/settings/get", "GET", None),
                ("/api/files", "GET", None),
                ("/api/queue/status", "GET", None),
            ]:
                try:
                    if method == "GET":
                        r = await c.get(f"{BASE}{path}")
                    else:
                        r = await c.post(f"{BASE}{path}", json=body)
                    print(f"  {method} {path:<24} -> {r.status_code}")
                except Exception as e:
                    print(f"  {method} {path:<24} -> ERR {type(e).__name__}")

            # 视频解析接口（不下载，只看解析）
            print()
            print("  测试 /api/video/parse（抖音）:")
            r = await c.post(f"{BASE}/api/video/parse", json={
                "url": "https://www.douyin.com/video/7689023840848006451"
            }, timeout=180)
            print(f"    HTTP {r.status_code}")
            if r.status_code == 200:
                d = r.json()
                print(f"    platform : {d.get('platform')}")
                print(f"    title    : {str(d.get('title'))[:50]}")
                print(f"    author   : {d.get('author')}")
                print(f"    has_url  : {bool(d.get('video_url'))}")
            else:
                print(f"    {r.text[:200]}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    print("=" * 62)
    print("测试 B: server 日志（确认浏览器预热与关闭）")
    print("=" * 62)
    try:
        out = proc.stdout.read() if proc.stdout else ""
        for line in out.split("\n"):
            if any(k in line for k in
                   ("browser", "浏览器", "Douyin", "douyin", "shutdown", "关闭")):
                print(f"  {line.strip()[:150]}")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
