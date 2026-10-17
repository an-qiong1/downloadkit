"""CREATE_NO_WINDOW 全仓覆盖回归测试（2026-10-17）

约定（交接文档坑 2）：GUI 打包版（console=False）里任何子进程调用点必须
带 creationflags=CREATE_NO_WINDOW，否则每首失败/转码的歌都会弹黑框。
本批修复前实测漏网的就是 motion_photo.py 的 3 处（挂在抖音实况照片主路径）。

静态扫描 downloadkit/ 与 server.py 的全部 subprocess.run / Popen /
create_subprocess_exec / create_subprocess_shell 调用点：
每个调用必须带 CREATE_NO_WINDOW（或 run.py 重启分支的 DETACHED_PROCESS），
除非命中"本来就允许弹/非 Windows 路径"的豁免清单。新增调用点漏标志会被
本测试直接拦红。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 扫描范围：GUI 进程会执行到的代码
SCAN_TARGETS = [ROOT / "server.py"] + sorted(
    (ROOT / "downloadkit").glob("*.py")
)

# 匹配四种进程创建调用
CALL_RE = re.compile(
    r"(subprocess\.run\(|subprocess\.Popen\(|"
    r"asyncio\.create_subprocess_exec\(|asyncio\.create_subprocess_shell\()"
)

# 取调用起始后这么长的文本作为"调用块"（够覆盖参数，极少跨行更多）
BLOCK = 420

# 豁免（每项附理由，改代码时别随手删）：
#   - explorer / open / xdg-open / startfile：用户主动"打开文件夹/文件"，本该有窗口响应
#   - networksetup：proxy.py 的 macOS 分支，Windows GUI 路径不执行
EXEMPT_MARKERS = ("'explorer'", "'open'", "'xdg-open'", "networksetup")

FLAG_MARKERS = ("CREATE_NO_WINDOW", "DETACHED_PROCESS")


def _iter_call_sites():
    for path in SCAN_TARGETS:
        text = path.read_text(encoding="utf-8")
        for m in CALL_RE.finditer(text):
            # 跳过注释行
            line_start = text.rfind("\n", 0, m.start()) + 1
            if text[line_start:m.start()].lstrip().startswith("#"):
                continue
            yield path, m.start(), text[m.start():m.start() + BLOCK]


def test_every_subprocess_site_has_no_window_flag():
    bad = []
    for path, pos, block in _iter_call_sites():
        # 截到括号配平前近似：第一个行末右括号簇之后若已出现豁免/标志就以首个为准
        head = block
        if any(k in head for k in EXEMPT_MARKERS):
            continue
        if not any(k in head for k in FLAG_MARKERS):
            lineno = path.read_text(encoding="utf-8")[:pos].count("\n") + 1
            bad.append(f"{path.name}:{lineno}: {head.splitlines()[0][:60]}")
    assert not bad, (
        "以下子进程调用点缺 CREATE_NO_WINDOW（GUI 打包版会弹黑框）：\n"
        + "\n".join(bad)
    )


def test_motion_photo_three_sites_covered():
    """本批修复直接钉死：motion_photo.py 的三处 ffmpeg/ffprobe 调用"""
    text = (ROOT / "downloadkit" / "motion_photo.py").read_text(encoding="utf-8")
    n_calls = len(CALL_RE.findall(text))
    n_flags = text.count("creationflags=CREATE_NO_WINDOW")
    assert n_calls == n_flags, (
        f"motion_photo.py 有 {n_calls} 处子进程调用但只有 {n_flags} 处带 flags"
    )
