"""P2 验收 —— 真实创作者实测「往回补 N 个」（exe 上跑）。

覆盖 PLAN P2 验收的最后一项：范围三种模式 × 水位线不重复，在
**打包后的 exe** 里用真实创作者走一遍完整链路：

  1. 笔吧评测室（水位线已建）设 backfill_n=2
  2. 手动检查 → 断言 backfilled=2、backfill_left=0
  3. 等 2 个视频真实下载完成（~/Downloads/DownloadKit/videos +2）
  4. 再查一轮 → 断言 backfilled=0（N 已满）且没有任何重复入队
  5. 范围复原 only_new（既有订阅数据不许留验收痕迹）

红线：
  · 会真实下载 2 个视频 —— 这是本脚本的全部意义，N 固定为 2
  · 只动笔吧评测室这一个订阅，跑完必须复原 only_new
  · 抖音限流：检查串行、轮询之间留间隔，绝不并发敲

用法（exe 已在运行）：
    .venv\\Scripts\\python.exe build\\test-exe-backfill.py
    .venv\\Scripts\\python.exe build\\test-exe-backfill.py --port 8765
"""
import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

# 笔吧评测室（已有订阅、水位线已建、enabled=1）
SEC_UID = "MS4wLjABAAAA9jVXMI9P5Gye45GdF88OIr1Frk2Gf1q7PS416m3PxGo"
N = 2
VIDEOS_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "DownloadKit", "videos")
DOWNLOAD_TIMEOUT = 600          # 2 个视频的下载+轮询上限（秒）


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_port() -> int:
    for p in range(8765, 8801):
        if port_open(p):
            return p
    raise SystemExit("没找到在跑的 downloadkit（8765-8800）")


def api(port: int, path: str, body=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        payload = e.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {e.code} on {path}: {payload[:400]}")


def video_count() -> int:
    if not os.path.isdir(VIDEOS_DIR):
        return 0
    n = 0
    for root, _dirs, files in os.walk(VIDEOS_DIR):
        n += len(files)
    return n


def wait_queue_idle(port: int, timeout: int) -> bool:
    """等下载队列清空；返回是否在超时前清空"""
    deadline = time.time() + timeout
    active_states = {"queued", "pending", "running", "downloading"}
    while time.time() < deadline:
        q = api(port, "/api/queue/status")
        active = [t for t in (q.get("tasks") or [])
                  if (t.get("status") or "") in active_states]
        if not active:
            return True
        time.sleep(5)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--verify", action="store_true",
                    help="补下已在上一轮完成（任务已入队），本轮只验证："
                         "下载真的落盘 + N 已封顶不再补 + 零重复")
    args = ap.parse_args()

    port = args.port or find_port()
    print(f"[0] exe 在跑，端口 {port} verify={args.verify}")

    before_files = video_count()

    # ---- 1. 设范围 backfill_n=2（幂等，复查也要它在位）----
    r = api(port, f"/api/subscriptions/{SEC_UID}/scope",
            {"scope": "backfill_n", "param": str(N)})
    rec = r.get("creator") or r
    assert rec.get("download_scope") == "backfill_n", r
    assert rec.get("scope_param") == str(N), r
    print(f"[1] 范围已设 backfill_n={N}")

    try:
        # ---- 2. 检查 ----
        r = api(port, f"/api/subscriptions/{SEC_UID}/check",
                {"download": True, "max_new": 3, "max_scrolls": 3})
        bf = r.get("backfilled") or 0
        print(f"[2] 检查结果: {r.get('message')!r} "
              f"backfilled={bf} left={r.get('backfill_left')}")
        if args.verify:
            # 上一轮已补满 2 个：count_backfilled 按水位线过滤 →
            # remaining=0 → 一个都不许再补，更不许产生新任务
            assert bf == 0, f"N=2 已满还在补 {bf} 个，重复下载！"
            assert not r.get("task_ids"), "复查产生了新任务"
        else:
            assert bf == N, f"该补 {N} 个，实际 {bf}"
            # left 只在真的有剩余时才报字段（既有设计），缺省 = 0
            assert (r.get("backfill_left") or 0) == 0, "N=2 应一次补满"
            assert len(set(r.get("task_ids") or [])) == N, "任务号不唯一"

        # ---- 3. 等真实下载完成 ----
        ok = wait_queue_idle(port, DOWNLOAD_TIMEOUT)
        assert ok, "下载队列超时未清空"
        time.sleep(3)
        after_files = video_count()
        added = after_files - before_files
        print(f"[3] 下载完成：videos {before_files} → {after_files}（+{added}）")
        if args.verify:
            # 续跑场景：before 可能是下完后的 3，也可能还在下载中。
            # 最终真相 = P1 红线基线 1 + 本轮恰好 2 个补下任务
            assert after_files == 3, \
                f"预期 1（基线）+ 2（本轮补下）= 3，实际 {after_files}"
        else:
            assert added == N, f"预期落盘 {N} 个，实际 +{added}"

        # ---- 4. 再查一轮：N 已满，绝不再补、绝不重复 ----
        r2 = api(port, f"/api/subscriptions/{SEC_UID}/check",
                 {"download": True, "max_new": 3, "max_scrolls": 3})
        print(f"[4] 复查结果: {r2.get('message')!r} "
              f"backfilled={r2.get('backfilled')} left={r2.get('backfill_left')}")
        assert (r2.get("backfilled") or 0) == 0, "N 已满还在补，重复下载！"
        assert not r2.get("task_ids"), "复查产生了新任务"
        time.sleep(3)
        final_files = video_count()
        assert final_files == after_files, \
            f"复查后文件数又变了 {after_files} → {final_files}，重复下载！"

        print("PASS: backfill_n 补下 N 个、下载落盘、复查零重复")
    finally:
        # ---- 5. 复原 only_new（无论成败都复原）----
        r = api(port, f"/api/subscriptions/{SEC_UID}/scope",
                {"scope": "only_new"})
        rec = r.get("creator") or r
        assert rec.get("download_scope") == "only_new", f"复原失败: {r}"
        print("[5] 范围已复原 only_new（既有数据无验收痕迹）")


if __name__ == "__main__":
    main()
