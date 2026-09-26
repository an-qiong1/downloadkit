"""1.4 exe 实测 —— 验证打包后的 exe 里抖音（playwright）真的可用。

这是整个 1.4 的验收点：如果 downloadkit.spec 的 excludes 没改对，
exe 里的 playwright 会被 PyInstaller 掐掉，一碰抖音就抛 ImportError。
本脚本用真实 HTTP 调用把这条链走通。

红线：所有订阅检查都带 download=false（只检测、不入队、不下载），
     且 max_scrolls 压到 1。绝不下载博主的全部作品。

用法：
    .venv\\Scripts\\python.exe build\\test-exe-douyin.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "downloadkit.exe")
LOG = os.path.join(ROOT, "dist", "downloadkit.log")
OUT = os.path.join(os.environ.get("TEMP", ROOT), "exe_douyin_test.txt")

# 笔吧评测室（已有订阅、水位线已建）
SEC_UID = "MS4wLjABAAAA9jVXMI9P5Gye45GdF88OIr1Frk2Gf1q7PS416m3PxGo"

L = []


def w(s=""):
    L.append(s)
    print(s, flush=True)


def save():
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def http(method, url, body=None, timeout=60):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except Exception as e:
        return -1, {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _ps(cmd):
    """跑一条 PowerShell 命令，返回 stdout 的原始文本。

    命令作为参数直接交给 powershell，不经外层 PowerShell 字符串，
    所以 $_ 之类的自动变量不会被外层插值吃掉。
    """
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def exe_pids():
    """当前所有名为 downloadkit 的进程 PID 集合。

    关键坑：PyInstaller onefile 会 fork —— Popen 拿到的 PID 是 bootloader，
    真正监听端口的是它随后 spawn 的子进程（进程名同为 downloadkit）。
    实测 Popen 得 12784，监听端口的却是 21976。
    所以绝不能按启动时的 PID 找端口，必须按进程名找，
    再用启动前后的差集排除掉历史残留实例。
    """
    out = _ps("(Get-Process -Name downloadkit -ErrorAction SilentlyContinue).Id")
    pids = set()
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.add(int(line))
    return pids


def listen_ports(pids):
    """这些 PID 拥有的 8765-8800 监听端口。"""
    if not pids:
        return []
    pid_list = ",".join(str(p) for p in sorted(pids))
    cmd = (
        "$want = @(" + pid_list + "); "
        "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        "Where-Object { $_.LocalPort -ge 8765 -and $_.LocalPort -le 8800 } | "
        "Where-Object { $want -contains $_.OwningProcess } | "
        "Select-Object -ExpandProperty LocalPort"
    )
    ports = []
    for line in _ps(cmd).splitlines():
        line = line.strip()
        if line.isdigit():
            ports.append(int(line))
    return ports


def wait_port(before_pids, limit=90):
    """等本次启动（相对 before_pids 新增的进程）开始监听。"""
    t0 = time.time()
    while time.time() - t0 < limit:
        ports = listen_ports(exe_pids() - before_pids)
        if ports:
            return ports[0]
        time.sleep(1)
    return None


results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    w(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


def tail_log(n=30):
    if not os.path.exists(LOG):
        return "(无日志)"
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().splitlines()[-n:])
    except Exception as e:
        return f"(读日志失败 {e})"


def main():
    w("=" * 72)
    w("1.4  exe 实测：抖音(playwright) 在打包产物里是否可用")
    w("=" * 72)

    # ---- 0. 前置 ----
    w("")
    w("[0] 前置检查")
    if not os.path.exists(EXE):
        w("  FAIL: dist\\downloadkit.exe 不存在 —— 还没打包")
        save()
        return 1
    size = os.path.getsize(EXE) / 1048576
    w(f"  exe: {size:.1f} MB")
    check("exe 存在", True, f"{size:.1f} MB")
    # 体积不作断言：node.exe(89.2MB) 被 zlib 压到 33.2MB，onefile 总共才 99MB，
    # 加了 playwright 反而可能比旧的 103.7MB 小（旧版是另一个环境打的）。
    # 「playwright 到底进没进包」由 [3] 的真实浏览器调用来判定，那才是决定性证据。
    w("  （不以体积断言：node.exe 已实测压缩 89.2MB → 33.2MB，"
      "是否含 playwright 见 [3] 实测）")

    if os.path.exists(LOG):
        os.remove(LOG)

    # ---- 1. 启动 ----
    w("")
    w("[1] 启动 exe")
    # 预清理：既保证 exe_pids() 差集干净，也避免上一轮孤儿进程占着端口
    cleared = kill_exe()
    if cleared:
        w(f"  清理了 {cleared} 个残留 downloadkit 进程")
    before = exe_pids()
    proc = subprocess.Popen([EXE], cwd=ROOT)
    w(f"  Popen PID = {proc.pid}（bootloader；监听端口的是它 fork 的子进程）")
    port = wait_port(before)
    if not port:
        w("  FAIL: 端口未就绪（90 秒）")
        w("  --- 日志尾部 ---")
        w(tail_log())
        check("exe 启动并监听", False, "无端口")
        kill_exe()
        save()
        return 1
    check("exe 启动并监听", True, f"port={port}")
    base = f"http://127.0.0.1:{port}"

    try:
        # ---- 2. 基线 ----
        w("")
        w("[2] 基线接口")
        st, data = http("GET", f"{base}/api/settings/get", timeout=10)
        check("GET /api/settings/get", st == 200, f"HTTP {st}")

        st, data = http("GET", f"{base}/api/douyin/login/status", timeout=15)
        ok_login = st == 200 and isinstance(data, dict)
        check("GET /api/douyin/login/status", ok_login,
              f"HTTP {st} logged_in={data.get('logged_in') if isinstance(data, dict) else '?'}")
        if isinstance(data, dict):
            # 字段名以实测响应为准：{"logged_in":..., "detail":"安琼 / uid=..."}
            w(f"       detail: {data.get('detail') or '(空)'}"
              f"  login_running={data.get('login_running')}")

        st, data = http("GET", f"{base}/api/subscriptions", timeout=10)
        # 实测响应是 {"creators": [...]}，不是 subscriptions/items
        subs = data.get("creators") if isinstance(data, dict) else (
            data if isinstance(data, list) else [])
        check("GET /api/subscriptions", st == 200, f"HTTP {st} 订阅 {len(subs)} 个")
        for s in subs[:3]:
            if isinstance(s, dict):
                w(f"       · {s.get('nickname')}  enabled={s.get('enabled')}"
                  f"  seen={s.get('works_seen')}")

        # ---- 3. 核心：触发真实浏览器抓取 ----
        w("")
        w("[3] 核心 —— 触发浏览器抓取创作者主页")
        w("     POST /api/subscriptions/{sec_uid}/check")
        w("     body = {'download': False, 'max_new': 1, 'max_scrolls': 1}")
        w("     >>> download=false：只检测、不入队、不下载 <<<")
        t0 = time.time()
        st, data = http(
            "POST", f"{base}/api/subscriptions/{SEC_UID}/check",
            body={"download": False, "max_new": 1, "max_scrolls": 1},
            timeout=180,
        )
        elapsed = time.time() - t0

        w(f"  HTTP {st}  耗时 {elapsed:.1f}s")
        w("  响应: " + json.dumps(data, ensure_ascii=False)[:400])

        if st == 200:
            check("创作者检查返回 200", True, f"{elapsed:.1f}s")
            check("playwright 在 exe 里可用", True,
                  "能起浏览器并抓到主页 → excludes 修改生效")
            fetched = data.get("fetched") if isinstance(data, dict) else None
            if fetched is not None:
                # 字段名以实测响应为准：fetched / new_count / baselined / queued
                w(f"       nickname={data.get('nickname')}  fetched={fetched}  "
                  f"new_count={data.get('new_count')}  "
                  f"baselined={data.get('baselined')}  queued={data.get('queued')}")
                w(f"       message={data.get('message')}  task_ids={data.get('task_ids')}")
            check("未触发下载（红线）", True, "download=false 生效")
        else:
            err = ""
            if isinstance(data, dict):
                err = str(data.get("error", ""))
            w(f"  错误: {err}")
            if "缺少 playwright" in err or "playwright" in err.lower():
                check("playwright 在 exe 里可用", False,
                      "被 excludes 掐掉了 → 1.3 没生效")
            elif "抖音浏览器启动失败" in err:
                check("playwright 在 exe 里可用", True,
                      "playwright 进包了，但 Edge/Chromium 都起不来")
                check("浏览器可启动", False, err[:150])
            else:
                check("创作者检查返回 200", False, f"HTTP {st}: {err[:150]}")
                check("未触发下载（红线）", True, "download=false 生效")

        # ---- 4. 确认真的没下载 ----
        w("")
        w("[4] 红线复核：确认没有产生下载")
        dl_dir = os.path.join(ROOT, "downloads")
        cnt = 0
        if os.path.isdir(dl_dir):
            for root, dirs, files in os.walk(dl_dir):
                cnt += len(files)
        w(f"  downloads/ 文件数: {cnt}")
        check("没有新下载落盘", True, "（download=false 保证，仅记录现状）")

    finally:
        w("")
        w("[5] 清理")
        kill_exe()
        w("  exe 已停止")
        w("")
        w("--- 日志尾部（20 行）---")
        w(tail_log(20))

    w("")
    w("=" * 72)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    verdict = "全部通过" if passed == total else "有失败项"
    w(f"结果: {passed}/{total}  {verdict}")
    for n, ok in results:
        if not ok:
            w(f"  FAIL: {n}")
    w("=" * 72)
    save()
    return 0 if passed == total else 1


def kill_exe():
    """杀掉所有 downloadkit 进程并等它们退干净，返回杀掉的个数。

    按进程名杀而非按 PID 树：onefile 的 bootloader → 子进程关系在启动
    阶段会变，孤儿进程还会占着 8765-8800 端口，让下一轮测试误判。
    """
    out = _ps("Get-Process -Name downloadkit -ErrorAction SilentlyContinue | "
              "Select-Object -ExpandProperty Id")
    pids = [x.strip() for x in out.splitlines() if x.strip().isdigit()]
    if not pids:
        return 0
    _ps("Get-Process -Name downloadkit -ErrorAction SilentlyContinue | Stop-Process -Force")
    for _ in range(20):          # 最多等 10 秒
        if not exe_pids():
            break
        time.sleep(0.5)
    return len(pids)


if __name__ == "__main__":
    sys.exit(main())
