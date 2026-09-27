"""下载目录结构：默认值、配置迁移、旧目录搬迁

2026-09-27 用户反馈：装完直接在系统下载目录下生成 music/、videos/、
animated/ 三个软件自建目录，很脏。改法是默认根目录变成
`~/Downloads/DownloadKit`，分类目录全收进这个总文件夹；老用户目录里
已经躺着的文件由 migrate_legacy_download_dirs() 启动时一次性搬。

三条安全红线各自一条用例钉死：
  1. 只动默认路径（自定义过的一律不碰）
  2. 同名冲突绝不覆盖
  3. 搬失败的留在原地，源目录非空就绝不删除
"""

from pathlib import Path

import pytest

import downloadkit.utils as utils
from downloadkit.utils import (
    DEFAULT_CONFIG,
    _migrate_config,
    get_download_subdir,
    migrate_legacy_download_dirs,
)

CATS = ("music", "videos", "animated", "images")


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """把家目录指到临时目录，别碰用户真实的 ~/Downloads。

    必须同时改 Path.home() 和 expanduser() 认的那几个环境变量 ——
    路径里带 `~` 的地方走的是 os.path.expanduser，只 patch Path.home 是没用的。
    """
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    for var in ("USERPROFILE", "HOME"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setenv("HOMEDRIVE", str(home)[:2])
    monkeypatch.setenv("HOMEPATH", str(home)[2:])
    monkeypatch.delenv("MUSIC_DL_DIR", raising=False)
    return home


def _write(p: Path, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _new_default_cfg() -> dict:
    """一份已经是最新默认值的 config（模拟 _migrate_config 跑完之后）"""
    return {"general": dict(DEFAULT_CONFIG["general"])}


# ---------------- 默认值 ----------------

def test_default_root_is_downloadkit_folder():
    gen = DEFAULT_CONFIG["general"]
    assert gen["download_dir"] == "~/Downloads/DownloadKit"
    for key, cat in (("download_dir_music", "music"),
                     ("download_dir_video", "videos"),
                     ("download_dir_animated", "animated"),
                     ("download_dir_images", "images")):
        # 分类目录必须收在总文件夹里，不能直接怼在系统下载目录下
        assert gen[key] == f"~/Downloads/DownloadKit/{cat}"


# ---------------- 配置值迁移（单跳到位） ----------------

@pytest.mark.parametrize("legacy", [
    "./downloads", "~/Downloads", "",
])
def test_migrate_root_to_latest_in_one_step(legacy):
    cfg = {"general": {"download_dir": legacy}}
    out, did = _migrate_config(cfg)
    assert did is True
    assert out["general"]["download_dir"] == "~/Downloads/DownloadKit"


@pytest.mark.parametrize("legacy,cat", [
    ("./downloads/music", "music"),
    ("~/Downloads/music", "music"),
    ("./downloads/videos", "videos"),
    ("~/Downloads/videos", "videos"),
    ("~/Downloads/animated", "animated"),
    ("~/Downloads/images", "images"),
])
def test_migrate_category_jumps_over_intermediate_default(legacy, cat):
    """中间那档 ~/Downloads/x 也要一次跳到 DownloadKit/x，不能等两次启动"""
    key = {"music": "download_dir_music", "videos": "download_dir_video",
           "animated": "download_dir_animated", "images": "download_dir_images"}[cat]
    cfg = {"general": {key: legacy}}
    out, did = _migrate_config(cfg)
    assert did is True
    assert out["general"][key] == f"~/Downloads/DownloadKit/{cat}"


def test_migrate_keeps_user_custom_path():
    cfg = {"general": {
        "download_dir": "D:/Media",
        "download_dir_music": "D:/Media/我爱听",
    }}
    out, _did = _migrate_config(cfg)
    # 用户手填的值一个字都不能动（缺失的字段仍会补默认值）
    assert out["general"]["download_dir"] == "D:/Media"
    assert out["general"]["download_dir_music"] == "D:/Media/我爱听"


def test_migrate_is_idempotent():
    cfg = {"general": dict(DEFAULT_CONFIG["general"])}
    out, did = _migrate_config(cfg)
    assert did is False
    assert out["general"]["download_dir"] == "~/Downloads/DownloadKit"


# ---------------- 分类子目录创建 ----------------

def test_get_download_subdir_creates_under_root(fake_home, monkeypatch):
    monkeypatch.setattr(utils, "load_config", lambda: _new_default_cfg())
    monkeypatch.delenv("MUSIC_DL_DIR", raising=False)

    sub = get_download_subdir("music")
    assert sub.is_dir()
    assert sub == fake_home / "Downloads" / "DownloadKit" / "music"
    # 总文件夹被建出来了，系统下载目录下没有散落的 music
    assert not (fake_home / "Downloads" / "music").exists()


# ---------------- 旧目录搬迁 ----------------

def test_migrate_moves_legacy_dirs_into_root(fake_home, monkeypatch):
    downloads = fake_home / "Downloads"
    _write(downloads / "music" / "晴天.mp3")
    _write(downloads / "videos" / "视频1.mp4")
    _write(downloads / "animated" / "动图.gif")
    (downloads / "images").mkdir()          # 空目录也应被清掉

    report = migrate_legacy_download_dirs(_new_default_cfg())

    assert report["moved"] == 3
    assert (downloads / "DownloadKit" / "music" / "晴天.mp3").is_file()
    assert (downloads / "DownloadKit" / "videos" / "视频1.mp4").is_file()
    assert (downloads / "DownloadKit" / "animated" / "动图.gif").is_file()
    # 搬空了的旧目录要删掉，没内容的空目录也删
    assert not (downloads / "music").exists()
    assert not (downloads / "videos").exists()
    assert not (downloads / "images").exists()
    assert report["errors"] == []


def test_migrate_never_overwrites_same_name(fake_home):
    downloads = fake_home / "Downloads"
    root = downloads / "DownloadKit" / "music"
    _write(root / "晴天.mp3", "新目录里已有的")
    _write(downloads / "music" / "晴天.mp3", "旧目录里的")

    report = migrate_legacy_download_dirs(_new_default_cfg())

    # 两边都得在，谁也不能被谁吞掉
    assert (root / "晴天.mp3").read_text(encoding="utf-8") == "新目录里已有的"
    renamed = root / "晴天 (1).mp3"
    assert renamed.is_file()
    assert renamed.read_text(encoding="utf-8") == "旧目录里的"
    assert not (downloads / "music").exists()
    assert report["errors"] == []


def test_migrate_leaves_custom_category_dir_alone(fake_home):
    downloads = fake_home / "Downloads"
    _write(downloads / "music" / "别动我.mp3")

    cfg = _new_default_cfg()
    cfg["general"]["download_dir_music"] = str(fake_home / "别的地方" / "music")

    report = migrate_legacy_download_dirs(cfg)

    assert (downloads / "music" / "别动我.mp3").is_file()   # 原样没动
    assert "skipped" in report["categories"]["music"]


def test_migrate_leaves_custom_root_alone(fake_home):
    downloads = fake_home / "Downloads"
    _write(downloads / "music" / "别动我.mp3")

    cfg = _new_default_cfg()
    cfg["general"]["download_dir"] = "D:/Media"

    report = migrate_legacy_download_dirs(cfg)
    assert "skipped" in report
    assert (downloads / "music" / "别动我.mp3").is_file()


def test_migrate_skipped_in_docker(fake_home, monkeypatch):
    downloads = fake_home / "Downloads"
    _write(downloads / "music" / "x.mp3")
    monkeypatch.setenv("MUSIC_DL_DIR", "/app/downloads")

    report = migrate_legacy_download_dirs(_new_default_cfg())
    assert "skipped" in report
    assert (downloads / "music" / "x.mp3").is_file()


def test_failed_move_keeps_source_dir(fake_home, monkeypatch):
    """单个文件搬不动（占用/权限）→ 留在原地、记错误、源目录不许删"""
    downloads = fake_home / "Downloads"
    _write(downloads / "music" / "好文件.mp3")
    _write(downloads / "music" / "坏文件.mp3")

    real_move = utils.shutil.move

    def _move(src, dst, *a, **kw):
        if "坏文件" in str(src):
            raise PermissionError("模拟文件被占用")
        return real_move(src, dst, *a, **kw)

    monkeypatch.setattr(utils.shutil, "move", _move)

    report = migrate_legacy_download_dirs(_new_default_cfg())

    assert report["moved"] == 1
    assert len(report["errors"]) == 1
    # 没搬动的那个必须还在原地
    assert (downloads / "music" / "坏文件.mp3").is_file()
    # 源目录非空 → 绝不能删
    assert (downloads / "music").is_dir()


def test_migrate_is_idempotent_on_second_run(fake_home):
    downloads = fake_home / "Downloads"
    _write(downloads / "music" / "晴天.mp3")

    first = migrate_legacy_download_dirs(_new_default_cfg())
    second = migrate_legacy_download_dirs(_new_default_cfg())

    assert first["moved"] == 1
    assert second.get("moved", 0) == 0
    assert (downloads / "DownloadKit" / "music" / "晴天.mp3").is_file()
    # 不能因为跑第二遍就造出 "晴天 (1).mp3"
    assert not (downloads / "DownloadKit" / "music" / "晴天 (1).mp3").exists()
