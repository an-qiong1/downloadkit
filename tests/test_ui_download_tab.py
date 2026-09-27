"""P1-1 回归：「已下载」+「下载队列」合并成「下载」页的静态一致性

2026-09-27 把侧边栏 7 个 tab 砍成 6 个：原 `files`（已下载）和 `queue`
（下载队列）合并进 `downloads`，页内用子视图 `state.downloadView`
（queue=进行中 / files=已完成）区分。

这层是纯静态检查，但正好锁住最容易出的两类事故：

  1. 漏改引用 —— 有 JS 还按 `activeTab === 'queue'` 判断，结果切到
     「下载」页后队列永远不刷新（轮询停摆），或反之下载完成不刷新列表
  2. 面板结构错位 —— 子视图容器少闭合一个 div，两个视图互相吞掉，
     点子 tab 看到的是空白

页面交互本身没法在 pytest 里跑（没有浏览器），所以这里断言**源码事实**：
条件表达式、面板 id、导航项、标题映射必须成套出现。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"


def _read(rel: str) -> str:
    return (STATIC / rel).read_text(encoding="utf-8")


HTML = _read("index.html")
APP = _read("js/app.js")
QUEUE = _read("js/queue.js")
FILES = _read("js/files.js")
MUSIC = _read("js/music.js")
RESOURCE = _read("js/resource.js")
UTILS = _read("js/utils.js")


# ---------------- 导航与面板 ----------------

def test_nav_has_downloads_and_drops_old_tabs():
    """侧边栏只剩 6 项，且用 downloads 取代 files/queue"""
    assert 'data-tab="downloads"' in HTML
    assert 'data-tab="files"' not in HTML, "旧「已下载」导航项没删干净"
    assert 'data-tab="queue"' not in HTML, "旧「下载队列」导航项没删干净"

    for tab in ("music", "resource", "subscriptions", "downloads",
                "collections", "settings"):
        assert f'data-tab="{tab}"' in HTML


def test_single_downloads_panel_with_two_views():
    """一个 panel + 两个子视图容器，旧 panel 不复存在"""
    assert 'id="panel-downloads"' in HTML
    assert 'id="dl-view-queue"' in HTML
    assert 'id="dl-view-files"' in HTML
    assert 'class="dl-subtabs"' in HTML

    assert 'id="panel-files"' not in HTML, "旧 panel-files 应已并入 panel-downloads"
    assert 'id="panel-queue"' not in HTML, "旧 panel-queue 应已并入 panel-downloads"

    # 默认「进行中」可见、「已完成」隐藏
    assert 'id="dl-view-files" style="display:none"' in HTML
    # 默认激活的是进行中
    assert 'data-view="queue" role="tab" aria-selected="true"' in HTML


def test_downloads_panel_tags_balanced():
    """panel-downloads 区域的 div 必须成对，否则子视图会互相吞掉"""
    start = HTML.index('id="panel-downloads"')
    # 从 panel 起始行往前回到该行行首
    start = HTML.rindex("\n", 0, start) + 1
    end = HTML.index("<!-- 收藏歌单面板 -->")
    block = HTML[start:end]

    opens = block.count("<div")
    closes = block.count("</div>")
    assert opens == closes, f"下载面板内 div 不配平：开 {opens} 闭 {closes}"


# ---------------- 轮询与刷新条件 ----------------

def test_queue_polling_tied_to_downloads_and_queue_view():
    """队列自动刷新只在「下载页 + 进行中视图」时跑（旧值是 activeTab==='queue'）"""
    assert "state.activeTab === 'downloads' && state.downloadView === 'queue'" in QUEUE
    assert "state.activeTab === 'queue'" not in QUEUE, "残留旧 tab 判断"


def test_download_finished_refresh_tied_to_downloads_and_files_view():
    """下载完成后刷新文件列表，只在「下载页 + 已完成视图」时跑"""
    needle = "state.activeTab === 'downloads' && state.downloadView === 'files'"
    assert needle in MUSIC, "music.js 漏改下载完成刷新条件"
    assert needle in RESOURCE, "resource.js 漏改下载完成刷新条件"
    for src, name in ((MUSIC, "music.js"), (RESOURCE, "resource.js")):
        assert "state.activeTab === 'files'" not in src, f"{name} 残留旧 tab 判断"


def test_app_switches_on_downloads_and_binds_subtabs():
    """switchTab 走 refreshDownloadView；子 tab 点击有绑定"""
    assert "tab === 'downloads'" in APP
    assert "refreshDownloadView()" in APP
    assert "tab === 'files'" not in APP
    assert "tab === 'queue'" not in APP
    assert "$$('.dl-subtab')" in APP
    assert "switchDownloadView(" in APP


def test_titles_and_state_dropped_old_tabs():
    """标题映射与全局状态跟着换掉，否则页头显示原始 tab 名"""
    assert "'downloads': '下载'" in UTILS
    assert "'files': '已下载'" not in UTILS
    assert "'queue': '下载队列'" not in UTILS
    assert "downloadView: 'queue'" in UTILS


def test_all_static_ids_referenced_by_js_exist():
    """JS 里 $('#id') 引用的 id 必须能找到（防子视图容器改名漏同步）

    动态弹窗（如 showRemotePathDialog 里 innerHTML 生成的 #rp-close）
    不在静态 HTML 里，所以把 JS 自己写死的 `id="..."` 也算进来。
    """
    import re

    ids = set(re.findall(r"\bid=\"([^\"]+)\"", HTML))
    for rel in ("js/app.js", "js/queue.js", "js/files.js"):
        ids.update(re.findall(r"\bid=\"([^\"]+)\"", _read(rel)))

    missing = []
    for rel in ("js/app.js", "js/queue.js", "js/files.js"):
        src = _read(rel)
        for ref in re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", src):
            if ref not in ids:
                missing.append(f"{rel}: #{ref}")
    assert not missing, "引用了不存在的元素：" + ", ".join(missing)
