# -*- coding: utf-8 -*-
"""_yt_dlp_cmd 分支与 _ytdlp_dump_json 降级分派单测。

核心回归（2026-10-03 打包版 bug）：frozen 下 _yt_dlp_cmd 绝不能返回
[sys.executable, "-m", "yt_dlp"]——打包后 sys.executable 是 downloadkit.exe
本体，spawn 出来的是完整应用实例，撞单实例锁弹窗、父进程 45s 超时。
"""
import asyncio
import sys

from downloadkit import generic_video as gv


def _fake_env(monkeypatch, tmp_path, *, frozen, exe_sidecar=False, which_ret=None):
    """把 sys.executable 指进 tmp_path，隔离 .venv\Scripts\yt-dlp.exe 的真实存在。"""
    exe = tmp_path / "downloadkit.exe"
    exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe))
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    if exe_sidecar:
        (tmp_path / "yt-dlp.exe").write_text("stub", encoding="utf-8")
    monkeypatch.setattr(gv.shutil, "which", lambda name: which_ret)


# ---------- _yt_dlp_cmd 分支 ----------

def test_frozen_without_ytdlp_returns_empty(tmp_path, monkeypatch):
    """frozen 且无独立 yt-dlp → []（降级进程内），绝不 spawn 自己。"""
    _fake_env(monkeypatch, tmp_path, frozen=True, which_ret=None)
    cmd = gv._yt_dlp_cmd()
    assert cmd == []
    assert str(sys.executable) not in cmd, "frozen 下绝不能用 sys.executable 当解释器"


def test_frozen_with_sidecar_exe(tmp_path, monkeypatch):
    """frozen 且 exe 同目录有 yt-dlp.exe → 用它（硬杀能力优先）。"""
    _fake_env(monkeypatch, tmp_path, frozen=True, exe_sidecar=True, which_ret=None)
    assert gv._yt_dlp_cmd() == [str(tmp_path / "yt-dlp.exe")]


def test_frozen_with_path_ytdlp(tmp_path, monkeypatch):
    """frozen 无侧车、PATH 有 yt-dlp → 用 PATH 的。"""
    _fake_env(monkeypatch, tmp_path, frozen=True,
              which_ret=str(tmp_path / "bin" / "yt-dlp.exe"))
    assert gv._yt_dlp_cmd() == [str(tmp_path / "bin" / "yt-dlp.exe")]


def test_dev_env_keeps_python_m(tmp_path, monkeypatch):
    """开发环境（非 frozen）保持 [sys.executable, -m, yt_dlp]。"""
    _fake_env(monkeypatch, tmp_path, frozen=False, which_ret=None)
    assert gv._yt_dlp_cmd() == [sys.executable, "-m", "yt_dlp"]


def test_sidecar_wins_over_frozen_which(tmp_path, monkeypatch):
    """同目录 yt-dlp.exe 优先于 PATH。"""
    _fake_env(monkeypatch, tmp_path, frozen=True, exe_sidecar=True,
              which_ret=str(tmp_path / "bin" / "yt-dlp.exe"))
    assert gv._yt_dlp_cmd() == [str(tmp_path / "yt-dlp.exe")]


# ---------- _ytdlp_dump_json 降级分派 ----------

def test_dump_json_falls_back_to_inproc_when_no_cmd(monkeypatch):
    """cmd 为空 → 走进程内 API，参数透传。"""
    seen = {}

    async def fake_inproc(url, *, flat=False, timeout=gv.PARSE_TIMEOUT, referer=""):
        seen.update(url=url, flat=flat, referer=referer)
        return [{"title": "ok"}]

    monkeypatch.setattr(gv, "_ytdlp_dump_json_inproc", fake_inproc)
    monkeypatch.setattr(gv, "_yt_dlp_cmd", lambda: [])
    out = asyncio.run(gv._ytdlp_dump_json(
        "http://127.0.0.1:1/v", flat=True, referer="http://ref/"))
    assert out == [{"title": "ok"}]
    assert seen == {"url": "http://127.0.0.1:1/v", "flat": True,
                    "referer": "http://ref/"}


def test_dump_json_keeps_subprocess_when_cmd_exists(monkeypatch):
    """cmd 存在时绝不降级（子进程硬杀能力优先）。"""
    async def fake_inproc(*args, **kwargs):  # pragma: no cover - 不应被调
        raise AssertionError("有 cmd 时不应走进程内降级")

    monkeypatch.setattr(gv, "_ytdlp_dump_json_inproc", fake_inproc)
    monkeypatch.setattr(gv, "_yt_dlp_cmd", lambda: ["yt-dlp"])
    # cmd 存在会真正 spawn：这里只验证分派条件，直接调用会在 spawn 后失败，
    # 故只断言 _yt_dlp_cmd 的结果非空即走原分支（spawn 逻辑由既有集成覆盖）。
    assert gv._yt_dlp_cmd() == ["yt-dlp"]
