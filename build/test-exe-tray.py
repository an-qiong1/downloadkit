"""1.5 exe 实测 —— 开机自启动(注册表) + 关闭到托盘(pystray)。

为什么必须打包装完再测：
  - autostart.get_status() 在源码模式恒返回 available=False（没有可自启
    的程序），只有 frozen 的 exe 才会真的去写 HKCU\\...\\Run。
  - 托盘链路 run.py 的 _start_tray() 依赖 pystray 进包 + ico 进 datas，
    这两件事只在打包产物里才成立。

三条断言链：
  1. 注册表   POST 开 -> 值落 HKCU\\...\\Run\\DownloadKit（路径带引号）
              POST 关 -> 值消失，且与测前状态一致
  2. 托盘     日志出现「托盘图标已启动」（pystray 进包且图标创建成功）
  3. 关闭行为 WM_CLOSE 后：
              close_to_tray=true  -> 进程仍活 + 窗口不可见（收进后台）
              close_to_tray=false -> 进程退出（原行为没被破坏）

红线：全程不触发任何下载，不动订阅检查接口。

用法（须先停掉源码 server，否则抢 Chromium profile / SQLite）：
    .venv\\Scripts\\python.exe build\\test-exe-tray.py
"""
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import winreg
from ctypes import wintypes

# 中文 Windows 控制台默认 GBK，打印 `«»`/emoji 这类字符会抛
# UnicodeEncodeError，把整个测试脚本直接打断（2026-09-27 实测崩在 step [7]，
# 差几步就跑完了）。保留原编码保证中文显示正常，只把打不出来的字符替换成 `?`
# —— 宁可日志里多个问号，也不能中断测试。
for _s in (sys.stdout, sys.stderr):
    try:
        if _s is not None:
            _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "downloadkit.exe")
LOG = os.path.join(ROOT, "dist", "downloadkit.log")
OUT = os.path.join(os.environ.get("TEMP", ROOT), "exe_tray_test.txt")

CONFIG = os.path.join(os.path.expanduser("~"), ".downloadkit", "config.toml")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DownloadKit"

WM_CLOSE = 0x0010

L = []
results = []


def w(s=""):
    L.append(s)
    print(s, flush=True)


def save():
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def check(name, ok, detail=""):
    results.append((name, ok))
    w(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))


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


# ---------------------------------------------------------------- 进程


def _ps(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def exe_pids():
    """当前名为 downloadkit 的进程 PID。

    onefile 必 fork：Popen 拿到的是 bootloader，真正干活的是子进程，
    所以只能按进程名 + 启动前后差集来认，绝不能信 Popen 的返回值。
    """
    out = _ps("(Get-Process -Name downloadkit -ErrorAction SilentlyContinue).Id")
    pids = set()
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.add(int(line))
    return pids


def listen_ports(pids):
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
    t0 = time.time()
    while time.time() - t0 < limit:
        ports = listen_ports(exe_pids() - before_pids)
        if ports:
            return ports[0]
        time.sleep(1)
    return None


def kill_exe():
    out = _ps("Get-Process -Name downloadkit -ErrorAction SilentlyContinue | "
              "Select-Object -ExpandProperty Id")
    pids = [x.strip() for x in out.splitlines() if x.strip().isdigit()]
    if not pids:
        return 0
    _ps("Get-Process -Name downloadkit -ErrorAction SilentlyContinue | Stop-Process -Force")
    for _ in range(20):
        if not exe_pids():
            break
        time.sleep(0.5)
    return len(pids)


# ---------------------------------------------------------------- 注册表


def read_run_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, VALUE_NAME)
            return v
    except (FileNotFoundError, OSError):
        return None


def delete_run_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
    except (FileNotFoundError, OSError):
        pass


# ---------------------------------------------------------------- 窗口


def top_windows(pid):
    """进程的顶层窗口句柄列表（pywebview 主窗口是顶层，WebView2 是子窗）。"""
    found = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND,
                                  wintypes.LPARAM)

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32 = ctypes.windll.user32
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.GetParent(hwnd) == 0:
            found.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(EnumProc(cb), 0)
    return found


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def is_visible(hwnd):
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


def pick_main_window(hwnds):
    """从进程的顶层窗口里挑出 pywebview 主窗口。

    踩过的坑（2026-09-26 实测两轮假阴性）：onefile 会在同一个进程里留下
    一个「PyInstaller Onefile Hidden Window」，枚举顺序还排在最前面。
    按「第一个有标题的窗口」挑必然选中它，而它本来就 IsWindowVisible=False，
    于是：
      - 判「窗口隐藏了」的断言永远不成立（6 秒后 visible=False）；
      - WM_CLOSE 发给它也不会触发退出（10 秒后进程仍活）。
    两轮 FAIL 看起来像功能没实现，其实是我把消息发错了窗口。
    """
    titled = [(h, window_title(h)) for h in hwnds]
    # 1) 可见 + 有标题 + 不是 PyInstaller 的辅助窗口 —— 正常情况
    for h, t in titled:
        if t and is_visible(h) and "PyInstaller" not in t:
            return h, t
    # 2) 有标题、不是 PyInstaller 的（窗口此刻可能已被隐藏，但仍是它）
    for h, t in titled:
        if t and "PyInstaller" not in t:
            return h, t
    # 3) 标题精确等于应用名（run.py create_window 的标题）
    for h, t in titled:
        if t == "DownloadKit":
            return h, t
    # 4) 兜底：任何可见窗口
    for h, t in titled:
        if is_visible(h):
            return h, t
    return None, None


def post_close(hwnd):
    return ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


# ---------------------------------------------------------------- 配置


def read_cfg_value(key="close_to_tray"):
    try:
        import tomllib
        with open(CONFIG, "rb") as f:
            cfg = tomllib.load(f)
        return (cfg.get("general") or {}).get(key)
    except Exception as e:
        return f"<err {e}>"


def write_cfg_tray(enabled):
    """直接改 config.toml 的一个布尔值（复用项目自己的 save_config，
    避免手写 TOML 把用户配置写坏）。"""
    code = (
        "import sys;"
        "sys.path.insert(0, %r);"
        "from downloadkit.utils import load_config, save_config;"
        "c = load_config();"
        "c.setdefault('general', {})['close_to_tray'] = %%s;"
        "save_config(c)" % ROOT
    ) % ("True" if enabled else "False")
    r = subprocess.run([os.path.join(ROOT, ".venv", "Scripts", "python.exe"),
                        "-c", code], capture_output=True, cwd=ROOT)
    if r.returncode != 0:
        w("  写配置失败: " + r.stderr.decode("utf-8", "replace")[:300])
        return False
    return True


def tail_log(n=30):
    if not os.path.exists(LOG):
        return "(无日志)"
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().splitlines()[-n:])
    except Exception as e:
        return f"(读日志失败 {e})"


def log_text():
    if not os.path.exists(LOG):
        return ""
    with open(LOG, encoding="utf-8", errors="replace") as f:
        return f.read()


def snapshot_files():
    """红线基线：三处可能落盘的位置各记一个文件数。"""
    counts = {}
    for name, d in [
        ("项目 downloads/", os.path.join(ROOT, "downloads")),
        ("dist/downloads", os.path.join(ROOT, "dist", "downloads")),
        # 2026-09-27 起默认根目录是 DownloadKit 总文件夹（分类目录收在里面）
        ("用户 Downloads\\DownloadKit\\videos",
         os.path.join(os.path.expanduser("~"), "Downloads", "DownloadKit", "videos")),
    ]:
        cnt = 0
        if os.path.isdir(d):
            for _, _, files in os.walk(d):
                cnt += len(files)
        counts[name] = cnt
    return counts


def launch(before, tray_enabled):
    if os.path.exists(LOG):
        os.remove(LOG)
    proc = subprocess.Popen([EXE], cwd=ROOT)
    port = wait_port(before)
    return proc, port


def main():
    w("=" * 72)
    w("1.5  exe 实测：开机自启动(注册表) + 关闭到托盘(pystray)")
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

    # 源码 server 在跑的话会抢 Chromium profile / SQLite，先拦下来
    py_on_port = _ps("Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
                     "Where-Object { $_.LocalPort -ge 8765 -and $_.LocalPort -le 8800 } | "
                     "Select-Object -ExpandProperty OwningProcess")
    blockers = []
    for line in py_on_port.splitlines():
        line = line.strip()
        if line.isdigit():
            name = _ps(f"(Get-Process -Id {line} -ErrorAction SilentlyContinue).ProcessName")
            blockers.append((line, name.strip()))
    if blockers:
        w("  FAIL: 8765-8800 已被占用，源码 server 必须先停：")
        for pid, name in blockers:
            w(f"    PID {pid} = {name}")
        w("  （exe 与源码 server 抢 Chromium profile 独占 + SQLite WAL，"
          "同时跑必出「未登录/订阅 0」假阴性）")
        check("端口空闲", False, "有源码 server 在跑")
        save()
        return 1
    check("端口空闲（无源码 server 抢资源）", True)

    # 注册表测前状态 —— 测完必须一模一样
    orig_run = read_run_value()
    w(f"  注册表测前: {VALUE_NAME} = {orig_run!r}")
    orig_tray = read_cfg_value()
    w(f"  config 测前: close_to_tray = {orig_tray!r}")

    killed = kill_exe()
    if killed:
        w(f"  清理了 {killed} 个残留 downloadkit 进程")

    files_before = snapshot_files()
    w(f"  文件基线: {files_before}")

    # ---- 1. 托盘模式启动 ----
    w("")
    w("[1] 以 close_to_tray=true 启动 exe")
    if not write_cfg_tray(True):
        check("写入 close_to_tray", False)
        cleanup(orig_run, orig_tray, files_before)
        return 1
    w(f"  config now: close_to_tray = {read_cfg_value()!r}")

    before = exe_pids()
    _, port = launch(before, True)
    if not port:
        w("  FAIL: 端口未就绪（90 秒）")
        w("  --- 日志尾部 ---")
        w(tail_log())
        check("exe 启动并监听", False, "无端口")
        kill_exe()
        cleanup(orig_run, orig_tray, files_before)
        save()
        return 1
    check("exe 启动并监听", True, f"port={port}")
    base = f"http://127.0.0.1:{port}"

    try:
        # ---- 2. 开机自启动：源码模式拿不到的那半截 ----
        w("")
        w("[2] GET /api/settings/autostart  (frozen 模式)")
        st, data = http("GET", f"{base}/api/settings/autostart", timeout=15)
        check("HTTP 200", st == 200, f"HTTP {st}")
        w("  响应: " + json.dumps(data, ensure_ascii=False))
        check("available=true（exe 才有可自启的程序）",
              isinstance(data, dict) and data.get("available") is True,
              data.get("reason") if isinstance(data, dict) else "")
        check("path 指向本 exe",
              isinstance(data, dict)
              and os.path.normcase(str(data.get("path") or ""))
              == os.path.normcase(EXE),
              data.get("path") if isinstance(data, dict) else "")

        w("")
        w("[3] POST /api/settings/autostart {enabled:true}")
        st, data = http("POST", f"{base}/api/settings/autostart",
                        {"enabled": True}, timeout=15)
        check("HTTP 200", st == 200, f"HTTP {st} {str(data)[:160]}")
        check("接口回读 enabled=true",
              isinstance(data, dict) and data.get("enabled") is True)
        w(f"  message: {data.get('message') if isinstance(data, dict) else '?'}")

        w("")
        w("[4] 注册表实查（这才是决定性证据，接口自己说了不算）")
        val = read_run_value()
        check("HKCU Run 里有 DownloadKit 值", val is not None, repr(val))
        if val:
            check("值是带引号的命令行（路径含空格才不会被拆）",
                  val.startswith('"') and val.endswith('"'), repr(val))
            check("指向 dist\\downloadkit.exe",
                  os.path.normcase(val.strip('"')) == os.path.normcase(EXE),
                  val)
        else:
            check("值是带引号的命令行", False, "值不存在")

        w("")
        w("[5] POST {enabled:false} 关掉")
        st, data = http("POST", f"{base}/api/settings/autostart",
                        {"enabled": False}, timeout=15)
        check("HTTP 200", st == 200, f"HTTP {st}")
        check("接口回读 enabled=false",
              isinstance(data, dict) and data.get("enabled") is False)
        check("注册表值已删除", read_run_value() is None,
              repr(read_run_value()))

        # 幂等：重复关闭不该报错
        st, data = http("POST", f"{base}/api/settings/autostart",
                        {"enabled": False}, timeout=15)
        check("重复关闭仍 200（幂等）", st == 200, f"HTTP {st}")

        # ---- 6. 托盘图标 ----
        w("")
        w("[6] 托盘图标是否创建成功（pystray 进包 + ico 进 datas）")
        txt = log_text()
        check("日志有「托盘图标已启动」", "托盘图标已启动" in txt)
        check("日志有「close_to_tray 已启用」",
              "close_to_tray 已启用" in txt)
        if "pystray 不可用" in txt:
            check("pystray 在 exe 里可用", False, "pystray 不可用（没进包）")
        else:
            check("pystray 在 exe 里可用", True)

        # ---- 7. 关闭窗口 -> 收到托盘 ----
        w("")
        w("[7] 关闭窗口（WM_CLOSE）应收到托盘而不是退出")
        pids = exe_pids() - before
        w(f"  本次新增进程: {sorted(pids)}")
        hwnds = []
        for pid in pids:
            hwnds += top_windows(pid)
        w("  顶层窗口:")
        for h in hwnds:
            w(f"      0x{h:X}  visible={is_visible(h)}  [{window_title(h)}]")
        target, ttitle = pick_main_window(hwnds)
        if target is None:
            check("找到主窗口", False, "枚举不到可用的顶层窗口")
        else:
            check("找到主窗口", True,
                  f"0x{target:X} [{ttitle}] visible={is_visible(target)}")
            vis_before = is_visible(target)
            post_close(target)
            w("  已投递 WM_CLOSE")
            # 给它 6 秒：隐藏是同步的，退出也该在 2 秒内可见
            hidden = False
            exited = False
            for _ in range(12):
                time.sleep(0.5)
                if not exe_pids() - before:
                    exited = True
                    break
                if vis_before and not is_visible(target):
                    hidden = True
                    break
            if exited:
                check("close_to_tray=true 时关闭 = 后台常驻", False,
                      "进程直接退出了 —— closing 事件没拦住")
            elif hidden:
                check("窗口已隐藏（收到托盘）", True)
                check("进程仍存活（后台常驻）", True,
                      f"pids={sorted(exe_pids() - before)}")
                check("HTTP 服务仍可访问（后台没断）",
                      http("GET", f"{base}/api/settings/autostart",
                           timeout=10)[0] == 200)
                time.sleep(1)
                check("日志有「窗口已收到托盘」", "窗口已收到托盘" in log_text())
            else:
                check("窗口已隐藏（收到托盘）", False,
                      f"6 秒后窗口仍 visible={is_visible(target)}")

        # 关闭路径：托盘菜单的「退出」走 destroy，这里用杀进程代替（UI 无法
        # 自动化点菜单），退出链路本身由 [8] 的 close_to_tray=false 覆盖。
        w("")
        w("  强制收尾本轮")
        kill_exe()
        check("本轮 exe 已停止", not exe_pids())

        # ---- 8. 回归：不开托盘时，关闭仍应正常退出 ----
        w("")
        w("[8] 回归：close_to_tray=false 时 WM_CLOSE 应真的退出")
        if not write_cfg_tray(False):
            check("改回 close_to_tray=false", False)
            return finish(orig_run, orig_tray, files_before, code=1)
        w(f"  config now: close_to_tray = {read_cfg_value()!r}")

        before2 = exe_pids()
        _, port2 = launch(before2, False)
        if not port2:
            check("第二轮启动", False, "无端口")
            w(tail_log())
            return finish(orig_run, orig_tray, files_before, code=1)
        check("第二轮启动并监听", True, f"port={port2}")

        pids2 = exe_pids() - before2
        hwnds2 = []
        for pid in pids2:
            hwnds2 += top_windows(pid)
        w("  第二轮顶层窗口:")
        for h in hwnds2:
            w(f"      0x{h:X}  visible={is_visible(h)}  [{window_title(h)}]")
        target2, ttitle2 = pick_main_window(hwnds2)
        if target2 is None:
            check("找到第二轮主窗口", False, "枚举不到可用的顶层窗口")
        else:
            check("找到第二轮主窗口", True,
                  f"0x{target2:X} [{ttitle2}] visible={is_visible(target2)}")
            post_close(target2)
            w("  已投递 WM_CLOSE")
            exited2 = False
            for _ in range(20):
                time.sleep(0.5)
                if not exe_pids() - before2:
                    exited2 = True
                    break
            check("关闭 = 退出（原行为未被破坏）", exited2,
                  "10 秒后进程仍存活" if not exited2 else "进程已退出")
            if exited2:
                check("日志有「Window closed by user」",
                      "Window closed by user" in log_text())
        kill_exe()

    finally:
        w("")
        w("[9] 清理")
        kill_exe()

    return finish(orig_run, orig_tray, files_before)


def finish(orig_run, orig_tray, files_before, code=0):
    """恢复环境：注册表、config、红线复核。"""
    w("")
    w("[10] 环境复原 + 红线复核")

    # 注册表：测前没有值就必须恢复成没有值
    now_val = read_run_value()
    if orig_run is None:
        delete_run_value()
        check("注册表已复原（测前无值 -> 现在无值）",
              read_run_value() is None, repr(read_run_value()))
    else:
        # 测前有值则原样写回
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, orig_run)
        except OSError as e:
            w(f"  写回原值失败: {e}")
        check("注册表已复原为测前原值",
              read_run_value() == orig_run, repr(read_run_value()))

    # config：恢复测前值
    w(f"  测前 close_to_tray = {orig_tray!r}")
    restored = write_cfg_tray(True if orig_tray is True else False)
    after = read_cfg_value()
    check("config close_to_tray 已复原",
          bool(after) == bool(orig_tray if orig_tray is not None else False),
          f"{orig_tray!r} -> {after!r}")

    # 红线：没有任何下载产生
    w("")
    w("  红线复核（本脚本全程未调用订阅检查/下载接口）")
    files_after = snapshot_files()
    for k in files_before:
        same = files_before[k] == files_after[k]
        check(f"未产生下载: {k}", same,
              f"{files_before[k]} -> {files_after[k]}")

    # 日志里也不该出现下载任务
    txt = log_text()
    bad = [kw for kw in ("入队", "开始下载", "下载完成") if kw in txt]
    check("日志无下载任务痕迹", not bad, ",".join(bad) or "干净")

    w("")
    w("--- 日志尾部（25 行）---")
    w(tail_log(25))

    w("")
    w("=" * 72)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    w(f"结果: {passed}/{total}  {'全部通过' if passed == total else '有失败项'}")
    for n, ok in results:
        if not ok:
            w(f"  FAIL: {n}")
    w("=" * 72)
    save()
    if code:
        return code
    return 0 if passed == total else 1


def cleanup(orig_run, orig_tray, files_before):
    """启动失败时的兜底复原。"""
    kill_exe()
    if orig_run is None:
        delete_run_value()
    write_cfg_tray(True if orig_tray is True else False)


if __name__ == "__main__":
    sys.exit(main())
