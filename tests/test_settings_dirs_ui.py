"""P1-3 回归：设置页只留「总下载目录」，分类目录降级为只读预览 + 高级折叠

2026-09-27 之前，设置页并排摊着 5 个目录输入框（总目录 + 4 个分类），
普通用户根本分不清该改哪个 —— 这一轮把它收成：

  * 主界面只有总目录一个输入框
  * 下面一块只读预览（#dir-preview-*），实时显示「各类文件实际存放在哪」
  * 4 个分类输入框原封不动挪进 <details id="dir-advanced"> 高级折叠里，
    id 一个没改，后端 5 个字段也一个没删（老配置照常兼容）

静态检查锁住两件事：

  1. 元素搬家搬丢 —— 高级折叠里的 input 少一个，settings.js 就会
     `$().value = ...` 抛空指针，设置页整个加载不出来
  2. 预览不同步 —— renderDirPreview 漏了一个调用时机，用户改了总目录
     预览还显示旧路径，会误以为下载落到了旧目录
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
SETTINGS = (STATIC / "js" / "settings.js").read_text(encoding="utf-8")

CATS = ["music", "video", "animated", "images"]


# ---------------- 结构：元素搬家不能搬丢 ----------------

def test_root_dir_input_is_the_only_visible_one():
    """主输入框在，且 4 个分类输入框被收进高级折叠里"""
    assert 'id="setting-download-dir"' in HTML
    assert 'id="dir-advanced"' in HTML

    # 4 个分类 input 必须都在 details 里面
    details_start = HTML.index('id="dir-advanced"')
    details_end = HTML.index("</details>", details_start)
    inner = HTML[details_start:details_end]
    for cat in CATS:
        assert f'id="setting-download-dir-{cat}"' in inner, f"{cat} 目录输入框没在高级折叠里"
        assert f'id="setting-browse-dir-{cat}"' in inner, f"{cat} 浏览按钮没在高级折叠里"


def test_dir_preview_block_covers_all_categories():
    """只读预览区四个槽位齐全，且在 details 之外（要常显）"""
    for cat in CATS:
        assert f'id="dir-preview-{cat}"' in HTML, f"预览缺少 {cat}"

    details_start = HTML.index('id="dir-advanced"')
    for cat in CATS:
        pos = HTML.index(f'id="dir-preview-{cat}"')
        assert pos < details_start, f"dir-preview-{cat} 被塞进折叠里了，常显才对"


def test_settings_js_keeps_all_five_dir_fields():
    """后端 5 个字段一个不能少（保存/回读要成对）"""
    for field in ("download_dir", "download_dir_music", "download_dir_video",
                  "download_dir_animated", "download_dir_images"):
        assert field in SETTINGS, f"settings.js 丢了字段 {field}"

    for cat in CATS:
        assert f"$('#setting-download-dir-{cat}')" in SETTINGS


# ---------------- 行为：预览必须跟着三个时机刷新 ----------------

def test_render_dir_preview_defined_and_called():
    """预览在加载、改根目录、改分类三条路径上都会刷新"""
    assert "function renderDirPreview()" in SETTINGS

    # 1) loadSettings 填完值后刷一次
    load_body = SETTINGS.split("window.loadSettings = function()")[1].split("\n  };")[0]
    assert "renderDirPreview()" in load_body, "loadSettings 没刷新预览"

    # 2) 根目录 change 后刷新
    change_body = SETTINGS.split("dirInput.addEventListener('change'")[1].split("});")[0]
    assert "renderDirPreview()" in change_body, "根目录 change 没刷新预览"

    # 3) 分类 input 自己改了也刷新
    assert "addEventListener('input', renderDirPreview)" in SETTINGS, \
        "高级折叠里改分类目录，预览不会跟着变"


def test_last_root_tracked_at_module_scope():
    """根目录的「上次值」必须是模块级的，不能是绑定时的闭包捕获

    2026-09-27 走查发现的坑：change 监听在初始化时绑，闭包里记的
    lastRoot 是空串；loadSettings 是异步的、之后才把根目录填进 input，
    于是用户第一次改根目录时 syncCategoryDirs(oldRoot='') 直接 return，
    4 个分类目录纹丝不动 —— 表面上「改了没反应」。
    """
    assert "var lastDirRoot" in SETTINGS
    # loadSettings 里要把异步填进去的值同步回 lastDirRoot
    load_body = SETTINGS.split("window.loadSettings = function()")[1].split("\n  };")[0]
    assert "lastDirRoot =" in load_body, "loadSettings 没刷新 lastDirRoot"
    # change 监听读写的都得是模块级变量
    change_body = SETTINGS.split("dirInput.addEventListener('change'")[1].split("});")[0]
    assert "lastDirRoot" in change_body
    assert "var lastRoot" not in SETTINGS, "还残留着旧的闭包 lastRoot"


def test_sync_category_dirs_still_derives_from_root():
    """改根目录 → 派生出来的分类跟着走（这条是 v0.4.1 的既有行为，别改没了）"""
    sync = SETTINGS.split("function syncCategoryDirs(")[1].split("\n    }")[0]
    for cat in ("music", "videos", "animated", "images"):
        assert f"'{cat}'" in sync, f"syncCategoryDirs 丢了分类 {cat}"
