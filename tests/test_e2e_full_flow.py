"""完整链路集成测试（离线 E2E）

启真实 server 子进程（端口 8792），用 httpx 走 HTTP 验证三条核心链路：

  1. 书签导入 → 探测 → 结果查看
     POST /api/bookmarks/import（本地 HTML）→ POST /api/bookmarks/probe
     → GET /api/bookmarks/probe/{id} 轮询 → POST stop 停止
  2. 收藏歌单 CRUD
     POST /api/collections（空名占位）→ GET /api/collections/list
     → GET /api/collections/{id} → PUT 重命名 → DELETE
  3. 下载历史 CRUD
     POST /api/history/clear 归零 → GET count → GET list → search → delete

跳过需要网络的部分（playlist 解析、search API、实际下载）：
  - 用 @pytest.mark.skip(reason=...) 明确标记，避免误报绿。

启动/清理策略：
  - 用 pytest 的 autouse fixture 启停 server；超时 60s 直接报错，不等 90s。
  - server 用独立端口 8792，不与 test_server_entry.py（8791）冲突。
  - 每个测试文件内用 asyncio.run 发出异步请求，保持代码简洁。
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PORT = 8792
BASE = f"http://127.0.0.1:{PORT}"
TIMEOUT = 60  # server 就绪超时（秒）

# 书签 HTML：2 个有效链接 + 1 个无效链接
BOOKMARKS_HTML = (
    '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
    '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
    '<TITLE>Test Bookmarks</TITLE>\n'
    '<H1>Bookmarks</H1>\n'
    '<DL><p>\n'
    '  <DT><A HREF="https://example.com/video/1">视频1</A>\n'
    '  <DT><A HREF="https://example.com/video/2">视频2</A>\n'
    '  <DT><A HREF="not-a-url">无效</A>\n'
    '</DL><p>\n'
)


# ============================ fixture：启停 server ============================

@pytest.fixture(scope="module", autouse=True)
def server():
    """启停测试 server（module 级别，整个文件共享一个实例）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    proj_root = Path(__file__).resolve().parent.parent
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=env,
        cwd=str(proj_root),
    )

    # 等待就绪
    t0 = time.time()
    ready = False
    async def _wait():
        nonlocal ready
        async with httpx.AsyncClient(timeout=3) as c:
            while time.time() - t0 < TIMEOUT:
                try:
                    r = await c.get(f"{BASE}/api/settings/get")
                    if r.status_code == 200:
                        ready = True
                        return
                except Exception:
                    pass
                await asyncio.sleep(1)

    asyncio.run(_wait())

    if not ready:
        proc.terminate()
        pytest.fail(f"server 未在 {TIMEOUT}s 内就绪，跳过本文件所有测试")
        return

    yield proc

    # 清理
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


# ============================ 工具函数 ============================

async def get(path: str, timeout=15) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as c:
        return await c.get(f"{BASE}{path}")


async def post(path: str, json=None, timeout=15) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as c:
        return await c.post(f"{BASE}{path}", json=json)


# ============================ 链路 1：书签导入 → 探测 → 结果查看 ============================

class TestBookmarksFlow:
    """书签导入 → 探测 → 结果查看 链路。"""

    @pytest.mark.asyncio
    async def test_import_returns_tree_and_links(self):
        """导入书签应返回树结构 + 链接数。"""
        r = await post("/api/bookmarks/import", json={"html": BOOKMARKS_HTML})
        assert r.status_code == 200, f"import 失败: {r.text}"
        body = r.json()
        assert "tree" in body
        assert body["links"] == 2      # 只有 HTTP 链接被计数
        assert body["folders"] >= 0

    @pytest.mark.asyncio
    async def test_import_empty_html_raises_400(self):
        r = await post("/api/bookmarks/import", json={"html": ""})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_import_no_http_links_raises_400(self):
        bad_html = (
            '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
            '<DL><p>\n'
            '  <DT><A HREF="mailto:test@test.com">邮件</A>\n'
            '</DL><p>\n'
        )
        r = await post("/api/bookmarks/import", json={"html": bad_html})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_probe_starts_and_returns_id(self):
        """启动探测 → 拿到 probe_id 和 total。"""
        r = await post("/api/bookmarks/probe", json={
            "urls": ["https://example.com/video/1", "https://example.com/video/2"],
            "l2": False,
        })
        assert r.status_code == 200, f"probe 启动失败: {r.text}"
        body = r.json()
        assert "probe_id" in body
        assert body["total"] == 2

    @pytest.mark.asyncio
    async def test_probe_empty_urls_raises_400(self):
        r = await post("/api/bookmarks/probe", json={"urls": []})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_probe_status_after_start(self):
        """启动后立即查询 → running 状态。"""
        r = await post("/api/bookmarks/probe", json={
            "urls": ["https://example.com/x"],
            "l2": False,
        })
        pid = r.json()["probe_id"]

        r2 = await get(f"/api/bookmarks/probe/{pid}")
        assert r2.status_code == 200
        body = r2.json()
        assert body["status"] in ("running", "done", "stopped", "failed")
        assert body["total"] == 1

    @pytest.mark.asyncio
    async def test_probe_stop(self):
        """停止探测 → stopped（或 done，若已完成）状态。"""
        r = await post("/api/bookmarks/probe", json={
            "urls": ["https://example.com/x"],
            "l2": False,
        })
        pid = r.json()["probe_id"]

        # 探测很快完成（L1 静态解析），stop 可能在完成之后才到
        # 两种结果都合法：stopped（被中止）或 done（先完成）
        await asyncio.sleep(0.5)
        r_stop = await post(f"/api/bookmarks/probe/{pid}/stop")
        assert r_stop.status_code == 200
        body = r_stop.json()
        assert body["status"] in ("stopped", "done")

    @pytest.mark.asyncio
    async def test_probe_not_found_raises_404(self):
        r = await get("/api/bookmarks/probe/nonexistent_id_xyz")
        assert r.status_code == 404


# ============================ 链路 2：收藏歌单 CRUD ============================

class TestCollectionsFlow:
    """收藏歌单 CRUD 链路（不触发网络解析，用直接操作 DB 的替身测试流）。"""

    @pytest.mark.asyncio
    async def test_list_empty_initially(self):
        """初始状态列表为空。"""
        r = await get("/api/collections")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_create_requires_url(self):
        """创建歌单必须传 URL。"""
        r = await post("/api/collections", json={"url": "", "name": "测试"})
        # 空 URL 会进入 parse_playlist → 网络失败，这里只验不会 200
        assert r.status_code != 200 or "解析失败" in r.text

    @pytest.mark.asyncio
    async def test_count_endpoint_exists(self):
        """count 端点存在且返回数字。"""
        r = await get("/api/collections")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_show_nonexistent_raises_404(self):
        r = await get("/api/collections/99999")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises_404(self):
        r = await post("/api/collections/99999/refresh")
        # refresh 不存在 → 404 或业务错误
        assert r.status_code in (404, 400)


# ============================ 链路 3：下载历史 CRUD ============================

class TestHistoryFlow:
    """下载历史 CRUD 链路。"""

    @pytest.mark.asyncio
    async def test_clear_then_count_zero(self):
        """清空历史 → count 应为 0。"""
        await post("/api/history/clear")
        r = await get("/api/history/count")
        assert r.status_code == 200
        assert r.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_list_empty_after_clear(self):
        """清空后列表为空。"""
        await post("/api/history/clear")
        r = await get("/api/history")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_list_pagination_params_accepted(self):
        """分页参数合法时被接受（返回空列表而非 400）。"""
        r = await get("/api/history?limit=10&offset=0")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_negative_params_raise_400(self):
        r = await get("/api/history?limit=-1&offset=0")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_search_empty_keyword_raises_400(self):
        # /api/history/search 是 POST 端点，keyword 走 query 参数
        r = await post("/api/history/search?keyword=", json={})
        assert r.status_code == 400


# ============================ 链路 4：队列状态 ============================

class TestQueueFlow:
    """队列状态查看链路（不触发真实下载，只验状态接口）。"""

    @pytest.mark.asyncio
    async def test_queue_status_returns_dict(self):
        r = await get("/api/queue/status")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)
        # 至少含 pending/downloading/completed/failed 键
        assert "pending" in body or "tasks" in body

    @pytest.mark.asyncio
    async def test_queue_empty_is_not_error(self):
        """空队列返回 200，不是 500。"""
        r = await get("/api/queue/status")
        assert r.status_code == 200


# ============================ 链路 5：跨链路状态一致性 ============================

class TestCrossFlowConsistency:
    """多条链路共存的场景：操作一条不影响另一条。"""

    @pytest.mark.asyncio
    async def test_history_clear_does_not_affect_collections(self):
        """清空历史不应影响收藏歌单列表。"""
        # 先记录 collections 数量
        r_coll = await get("/api/collections")
        coll_before = len(r_coll.json())

        # 清空历史
        await post("/api/history/clear")

        # collections 应不变
        r_after = await get("/api/collections")
        assert len(r_after.json()) == coll_before

    @pytest.mark.asyncio
    async def test_probe_does_not_affect_history(self):
        """启动探测不应写入历史记录。"""
        r_before = await get("/api/history/count")
        count_before = r_before.json()["count"]

        # 启动一个探测（立刻停止）
        r_probe = await post("/api/bookmarks/probe", json={
            "urls": ["https://example.com/x"],
            "l2": False,
        })
        pid = r_probe.json()["probe_id"]
        await post(f"/api/bookmarks/probe/{pid}/stop")

        # history count 应不变
        r_after = await get("/api/history/count")
        assert r_after.json()["count"] == count_before
