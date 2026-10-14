#!/usr/bin/env python3
"""download_content 的 output_dir 生效 + 扩展名对齐魔数 回归

2026-10-14 修的两个问题：
  A. output_dir 曾被静默忽略（docstring 标「已废弃」但各分支一律用
     get_download_subdir），导致 CLI 的 -o 形同虚设。
     现在：None → 走配置分类目录（历史行为不变）；指定 → output_dir/<分类>。
  B. 图文 file_ext 写死 jpg，实际常返回 WEBP，落盘后按魔数改名。
     同时 _existing_target 要能按 stem 兜底，否则改过名的文件会被重下。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from downloadkit.douyin import (
    DouyinContent,
    ContentType,
    _align_ext,
    _existing_target,
    _resolve_out_dir,
)


def _write(p: Path, magic: bytes, tail: int = 64) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(magic + b"\0" * tail)
    return p


class TestAlignExt:
    """B: 落盘后按魔数修正扩展名"""

    @pytest.mark.parametrize("magic,expect", [
        (b"\xff\xd8\xff\xe0" + b"\0" * 8, "jpg"),
        (b"\x89PNG\r\n\x1a\n" + b"\0" * 4, "png"),
        (b"RIFF\x00\x00\x00\x00WEBP" + b"\0" * 2, "webp"),
        (b"\x00\x00\x00\x18ftypisom" + b"\0" * 2, "mp4"),
    ])
    def test_renames_to_real_type(self, tmp_path, magic, expect):
        # 起名用一个必然错误的扩展名（源 ≠ 目标），否则「本来就对」会跳过改名
        wrong = next(e for e in ("jpg", "png", "webp", "mp4") if e != expect)
        p = _write(tmp_path / f"a.{wrong}", magic)
        out = _align_ext(p)
        assert out.suffix == f".{expect}", f"期望 .{expect}，实际 {out.suffix}"
        assert out.exists()
        assert not p.exists()
        assert out.read_bytes()[:len(magic)] == magic  # 只改名不重编码

    def test_keeps_name_when_ext_already_correct(self, tmp_path):
        """装 JPEG 的 .jpg 不该被动（上面参数化要求源≠目标，这里补这条）"""
        p = _write(tmp_path / "a.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 8)
        assert _align_ext(p) == p
        assert p.exists()

    def test_keeps_correct_ext(self, tmp_path):
        p = _write(tmp_path / "a.webp", b"RIFF\x00\x00\x00\x00WEBP" + b"\0" * 8)
        out = _align_ext(p)
        assert out == p
        assert p.exists()

    def test_jpeg_alias_not_renamed(self, tmp_path):
        """`.jpeg` 也是 JPEG，不该被改成 `.jpg`"""
        p = _write(tmp_path / "a.jpeg", b"\xff\xd8\xff\xe0" + b"\0" * 8)
        assert _align_ext(p) == p

    def test_unknown_magic_keeps_name(self, tmp_path):
        p = _write(tmp_path / "a.jpg", b"XXXX" + b"\0" * 8)
        assert _align_ext(p) == p
        assert p.exists()

    def test_truncated_file_keeps_name(self, tmp_path):
        p = tmp_path / "a.jpg"
        p.write_bytes(b"\xff\xd8")  # 短于 12 字节
        assert _align_ext(p) == p

    def test_missing_file_returns_input(self, tmp_path):
        p = tmp_path / "nope.jpg"
        assert _align_ext(p) == p

    def test_does_not_overwrite_existing_target(self, tmp_path):
        _write(tmp_path / "a.webp", b"RIFF\x00\x00\x00\x00WEBP" + b"\0" * 8)
        src = _write(tmp_path / "a.jpg", b"RIFF\x00\x00\x00\x00WEBP" + b"\0" * 8)
        out = _align_ext(src)
        assert out == src, "目标已存在时不应覆盖"
        assert src.exists()


class TestExistingTarget:
    """B 的配套：改过扩展名的文件必须还能被「已存在」预检认出来"""

    def test_finds_by_exact_name(self, tmp_path):
        p = _write(tmp_path / "a.jpg", b"\xff\xd8" + b"\0" * 8)
        assert _existing_target([tmp_path / "a.jpg"]) == p

    def test_falls_back_to_same_stem_other_ext(self, tmp_path):
        """候选是 .jpg、磁盘上是 .webp（被 _align_ext 改过）→ 必须命中"""
        real = _write(tmp_path / "a.webp", b"RIFF\x00\x00\x00\x00WEBP" + b"\0" * 8)
        hit = _existing_target([tmp_path / "a.jpg"])
        assert hit == real, "改过名的文件若认不出，会重下出第二份"

    def test_ignores_unrelated_ext(self, tmp_path):
        """同名但不是媒体扩展名（如 .txt）不算命中"""
        _write(tmp_path / "a.txt", b"hello")
        assert _existing_target([tmp_path / "a.jpg"]) is None

    def test_none_candidate_skipped(self, tmp_path):
        real = _write(tmp_path / "b.jpg", b"\xff\xd8" + b"\0" * 8)
        assert _existing_target([None, tmp_path / "b.jpg"]) == real

    def test_returns_none_when_absent(self, tmp_path):
        assert _existing_target([tmp_path / "x.jpg"]) is None


class TestResolveOutDir:
    """A: output_dir 生效规则"""

    def test_none_uses_config_category_dir(self, tmp_path, monkeypatch):
        """None → 走 get_download_subdir，即配置的分类目录（历史行为）"""
        fake = tmp_path / "cfg_videos"
        monkeypatch.setattr("downloadkit.douyin.get_download_subdir",
                            lambda cat: fake)
        assert _resolve_out_dir("videos", None) == fake

    def test_specified_overrides_config(self, tmp_path, monkeypatch):
        """指定 → output_dir/<分类>，且优先于配置"""
        called = []
        monkeypatch.setattr("downloadkit.douyin.get_download_subdir",
                            lambda cat: called.append(cat) or tmp_path / "cfg")
        root = tmp_path / "mine"
        out = _resolve_out_dir("videos", root)
        assert out == root / "videos"
        assert out.exists(), "目录应被创建"
        assert not called, "指定了 output_dir 就不该再查配置"


class TestSignature:
    """A: 默认值必须是 None，否则所有不传参的调用方行为都会变"""

    def test_download_content_default_is_none(self):
        import inspect
        from downloadkit.douyin import download_content
        default = inspect.signature(download_content).parameters["output_dir"].default
        assert default is None, f"默认值必须 None，实际 {default!r}"

    def test_fetch_default_is_none(self):
        import inspect
        from downloadkit.douyin import fetch
        assert inspect.signature(fetch).parameters["output_dir"].default is None

    def test_download_video_default_is_none(self):
        import inspect
        from downloadkit.douyin import download_video
        assert inspect.signature(download_video).parameters["output_dir"].default is None

    def test_no_stale_default_dir_strings(self):
        """源码里不该再残留已废弃的 './downloads' 默认值"""
        import downloadkit.douyin as douyin_mod
        src = Path(douyin_mod.__file__).read_text(encoding="utf-8")
        assert 'output_dir: str | Path = "./downloads"' not in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
