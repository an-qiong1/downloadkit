"""T1：让 batch_size 真正生效（按批独立并发额度）

背景：UI 提交歌单批量下载时传 batch_size=5，但这个值此前只被记进任务
信息，真实并发由全局写死的 max_concurrent=3 决定。现在批任务走独立额度
（lane），要守住三条：

  1. **批内并发真的到 batch_size**：测 5 路时，同时在跑的任务数能达到 5，
     不能被全局默认的 3 卡住。
  2. **不挤占其他任务**：批任务占满自己的额度时，普通任务（视频等）仍能
     按全局额度正常跑；反之批任务也不吃全局额度。
  3. **额度要归还、不泄漏**：批次结束后 lane 释放，Semaphore 不会只涨不跌
     （涨了就等于并发上限失效）。
"""

import asyncio

import pytest

from downloadkit.download_queue import DownloadQueue, TaskStatus


async def _run_until(q, done_event, timeout=5.0):
    """后台跑队列，直到 done_event 置位或超时，然后停队列。"""
    runner = asyncio.create_task(q.start())
    try:
        await asyncio.wait_for(done_event.wait(), timeout=timeout)
    finally:
        await q.stop()
        try:
            await asyncio.wait_for(runner, timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            runner.cancel()
    return q


def _probe_tasks(q, lane, size, count, peak, gate):
    """造 count 个任务：每个进入时记峰值并发，全部到齐后再一起放行。"""

    async def _func(task):
        peak["cur"] += 1
        peak["max"] = max(peak["max"], peak["cur"])
        peak["seen"].append(task.task_id)
        if len(peak["seen"]) >= count:
            gate.set()
        # 等所有任务都启动起来，确保峰值并发真的能观察到
        await asyncio.wait_for(gate.wait(), timeout=5.0)
        peak["cur"] -= 1

    async def _add_all():
        for i in range(count):
            await q.add_task(
                task_id=f"{lane}-{i}", url="u", platform="soda",
                title=f"t{i}", download_func=_func,
                lane=lane, lane_size=size,
            )

    return _add_all


@pytest.mark.asyncio
async def test_batch_lane_reaches_batch_size_above_global_limit():
    """batch_size=5 时真有 5 路并发，不被全局默认 3 卡住（T1 核心验收）"""
    q = DownloadQueue(max_concurrent=3)
    peak = {"cur": 0, "max": 0, "seen": []}
    gate = asyncio.Event()

    await _probe_tasks(q, "batch:t", 5, 5, peak, gate)()

    await _run_until(q, gate)

    assert peak["max"] == 5, (
        f"batch_size=5 只跑出了 {peak['max']} 路并发 —— 全局 max_concurrent=3 "
        f"仍在限制批任务"
    )


@pytest.mark.asyncio
async def test_batch_lane_does_not_consume_global_quota():
    """批任务占额度不影响普通任务：两套额度互相独立

    全局额度 2、批额度 5，两边共 7 个任务全部挂起等待。若额度是共享
    的（都从全局 3 里取），7 个不可能同时在跑 —— 这是"互不挤占"最直接
    的反证。
    """
    q = DownloadQueue(max_concurrent=2)
    batch_peak = {"cur": 0, "max": 0, "seen": []}
    normal_peak = {"cur": 0, "max": 0, "seen": []}
    all_started = asyncio.Event()
    release = asyncio.Event()

    def _mk(peak):
        async def _func(task):
            peak["cur"] += 1
            peak["max"] = max(peak["max"], peak["cur"])
            peak["seen"].append(task.task_id)
            if len(batch_peak["seen"]) + len(normal_peak["seen"]) >= 7:
                all_started.set()
            await release.wait()
            peak["cur"] -= 1
        return _func

    for i in range(5):
        await q.add_task(
            task_id=f"b{i}", url="u", platform="soda", title=f"b{i}",
            download_func=_mk(batch_peak), lane="batch:iso", lane_size=5,
        )
    for i in range(2):
        await q.add_task(
            task_id=f"n{i}", url="u", platform="douyin", title=f"n{i}",
            download_func=_mk(normal_peak),
        )

    runner = asyncio.create_task(q.start())
    try:
        # 7 个必须同时在跑，否则就是额度被共用/互相挤占
        await asyncio.wait_for(all_started.wait(), timeout=5.0)
    finally:
        release.set()
        await q.stop()
        try:
            await asyncio.wait_for(runner, timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            runner.cancel()

    assert batch_peak["max"] == 5, "批任务受自己的额度限制"
    assert normal_peak["max"] == 2, "普通任务受全局额度限制"
    assert len(normal_peak["seen"]) == 2, (
        "批任务占额度时普通任务起不来 —— 两套额度没有真正隔离"
    )


@pytest.mark.asyncio
async def test_lane_released_after_batch():
    """lane 可显式释放，且不会让额度只涨不跌"""
    q = DownloadQueue(max_concurrent=3)
    lim = q.ensure_lane("batch:x", 5)
    assert q.lane_sizes["batch:x"] == 5
    assert lim._value == 5

    assert q.release_lane("batch:x") is True
    assert "batch:x" not in q.lane_sizes
    assert q.release_lane("batch:x") is False, "重复释放不应报错"


@pytest.mark.asyncio
async def test_lane_size_fixed_on_first_use():
    """同一 lane 重复 ensure 不换对象：等在旧额度上的任务不能被饿死"""
    q = DownloadQueue(max_concurrent=3)
    first = q.ensure_lane("batch:y", 5)
    second = q.ensure_lane("batch:y", 9)
    assert first is second, "换了 Semaphore 对象会让等待者永远等不到"
    assert q.lane_sizes["batch:y"] == 5, "首次额度生效，后续 size 被忽略"


def test_set_max_concurrent_applies():
    """死配置 general.max_concurrent 现在真能改全局上限"""
    q = DownloadQueue(max_concurrent=3)
    assert q.set_max_concurrent(7) == 7
    assert q.max_concurrent == 7
    assert q._semaphore._value == 7
    # 下限保护：0/负数会造出永久卡死的队列
    assert q.set_max_concurrent(0) == 1


@pytest.mark.asyncio
async def test_process_task_direct_call_does_not_leak_quota():
    """直接调 _process_task（不经 start）不取额度，因此也不能归还"""
    q = DownloadQueue(max_concurrent=1)
    before = q._semaphore._value

    async def _func(task):
        pass

    task = await q.add_task(
        task_id="direct", url="u", platform="test", title="t",
        download_func=_func,
    )
    await q._process_task(task, _func)

    assert task.status == TaskStatus.COMPLETED
    assert q._semaphore._value == before, (
        "没取额度却归还，Semaphore 只涨不跌 → 并发上限失效"
    )


# ---------------- 服务端端点接线 ----------------


def _fake_playlist(n=5):
    from downloadkit.platforms.base import PlaylistInfo, SongInfo

    return PlaylistInfo(
        name="测试歌单", platform="soda", song_count=n,
        songs=[
            SongInfo(title=f"歌{i}", artist=f"歌手{i}", album="",
                     platform="soda", song_id=f"sid{i}")
            for i in range(n)
        ],
    )


@pytest.fixture
def batch_env(monkeypatch):
    """隔离的队列 + _downloads + 假歌单解析（不入真实下载）"""
    import server

    q = DownloadQueue(max_concurrent=3)
    d = {}
    monkeypatch.setattr(server, "download_queue", q)
    monkeypatch.setattr(server, "_downloads", d)

    def _use_playlist(n):
        async def _fake(url):
            return _fake_playlist(n)
        monkeypatch.setattr(server, "parse_playlist", _fake)

    return server, q, d, _use_playlist


@pytest.mark.asyncio
async def test_batch_endpoint_uses_own_lane_not_global(batch_env):
    """端点必须给批任务开独立额度，而不是吃全局额度"""
    server, q, d, use_playlist = batch_env
    use_playlist(5)

    r = await server.api_playlist_batch_download(
        server.PlaylistBatchDownloadRequest(url="https://qishui.douyin.com/s/x",
                                            batch_size=5)
    )

    assert r["batch_size"] == 5
    tid = r["task_id"]
    lane = f"batch:{tid}"
    assert q.lane_sizes.get(lane) == 5, "batch_size 没有变成独立额度"
    # 全局额度不受影响
    assert q.max_concurrent == 3
    assert q._semaphore._value == 3, "批任务挤占了全局额度"
    # 每个任务挂在同一 lane 上
    assert all(t.lane == lane for t in q.active_tasks.values())
    assert d[tid]["batch_size"] == 5


@pytest.mark.asyncio
async def test_batch_endpoint_clamps_batch_size(batch_env):
    """batch_size 超界要被夹到 [1, total]，不许造出 0 额度"""
    server, q, d, use_playlist = batch_env
    use_playlist(2)

    r = await server.api_playlist_batch_download(
        server.PlaylistBatchDownloadRequest(url="u", batch_size=99)
    )
    assert r["batch_size"] == 2, "不能超过总曲目数"
    assert q.lane_sizes[f"batch:{r['task_id']}"] == 2


@pytest.mark.asyncio
async def test_batch_status_finishes_when_all_songs_done(batch_env, monkeypatch):
    """全部曲目到终态后 status 必须变 done（否则前端进度条永远转）"""
    server, q, d, use_playlist = batch_env
    use_playlist(3)

    class _FakePath:
        name = "歌.mp3"

    async def _ok(song, task_id=None):
        return _FakePath()

    monkeypatch.setattr(server, "download_song", _ok)

    r = await server.api_playlist_batch_download(
        server.PlaylistBatchDownloadRequest(url="u", batch_size=3)
    )
    tid = r["task_id"]
    assert d[tid]["status"] == "downloading"

    # 走真实的 download_func（含计分 + finally 收尾）
    for idx in range(3):
        t = q.active_tasks[f"{tid}_s{idx}"]
        await t.download_func(t)

    assert d[tid]["completed"] == 3
    assert d[tid]["status"] == "done", (
        "所有曲目完成后批任务仍是 downloading —— 前端进度条永远不会停"
    )
    assert f"batch:{tid}" not in q.lane_sizes, "批结束应释放 lane"


@pytest.mark.asyncio
async def test_batch_status_done_when_some_fail(batch_env, monkeypatch):
    """失败也是终态：有曲目失败仍要终结，不能卡在 downloading"""
    server, q, d, use_playlist = batch_env
    use_playlist(2)

    async def _none(song, task_id=None):
        return None  # 无直链 = 失败分支

    monkeypatch.setattr(server, "download_song", _none)

    r = await server.api_playlist_batch_download(
        server.PlaylistBatchDownloadRequest(url="u", batch_size=2)
    )
    tid = r["task_id"]

    for idx in range(2):
        t = q.active_tasks[f"{tid}_s{idx}"]
        await t.download_func(t)

    assert d[tid]["failed"] == 2
    assert d[tid]["status"] == "done", "失败曲目也是终态，批任务必须终结"


@pytest.mark.asyncio
async def test_batch_status_not_done_while_pending(batch_env, monkeypatch):
    """还有曲目没跑完时不许提前标 done（避免前端过早收工）"""
    server, q, d, use_playlist = batch_env
    use_playlist(3)

    class _FakePath:
        name = "歌.mp3"

    async def _ok(song, task_id=None):
        return _FakePath()

    monkeypatch.setattr(server, "download_song", _ok)

    r = await server.api_playlist_batch_download(
        server.PlaylistBatchDownloadRequest(url="u", batch_size=3)
    )
    tid = r["task_id"]

    # 只跑完 2/3
    for idx in range(2):
        t = q.active_tasks[f"{tid}_s{idx}"]
        await t.download_func(t)

    assert d[tid]["status"] == "downloading", (
        "3 首只完成 2 首就标 done，前端会漏报最后一首"
    )


# ---------------- P0-1：一键停止批任务 ----------------


@pytest.mark.asyncio
async def test_batch_cancel_marks_pending_and_finalizes(batch_env, monkeypatch):
    """停止端点：已完成的保留，未起跑/在跑的一律置取消并终结批状态"""
    server, q, d, use_playlist = batch_env
    use_playlist(5)

    class _FakePath:
        name = "歌.mp3"

    async def _ok(song, task_id=None):
        return _FakePath()

    monkeypatch.setattr(server, "download_song", _ok)

    r = await server.api_playlist_batch_download(
        server.PlaylistBatchDownloadRequest(url="u", batch_size=5)
    )
    tid = r["task_id"]

    # 先正常跑完 2 首
    for idx in range(2):
        t = q.active_tasks[f"{tid}_s{idx}"]
        await t.download_func(t)

    res = await server.api_playlist_batch_cancel(tid)

    assert res["status"] == "cancelled"
    assert res["cancelled"] == 3, "剩余 3 首都应被计入取消"
    assert d[tid]["status"] == "cancelled"
    # 已完成条目不受影响
    assert d[tid]["completed"] == 2
    assert d[tid]["songs"][0]["status"] == "completed"
    # 未起跑的：记账 cancelled + 队列取消标志都置上（download_song
    # 第一行靠后者真实中断）
    for idx in range(2, 5):
        assert d[tid]["songs"][idx]["status"] == "cancelled"
        assert q.is_cancelled(f"{tid}_s{idx}"), "队列取消标志没置上"


@pytest.mark.asyncio
async def test_batch_cancel_final_after_cancel_keeps_cancelled(batch_env, monkeypatch):
    """停止后剩余曲收尾（finally 触发 _finalize_batch）不许把批状态覆盖回 done

    这是"一键停止"与收尾的竞态防护：cancel 端点立即置 cancelled，但
    在跑的曲稍后才在数据块边界抛 CancelException，其 finally 会调
    _finalize_batch —— 若那里无条件标 done，前端就会看到"已取消"闪回
    "已完成"。
    """
    server, q, d, use_playlist = batch_env
    use_playlist(2)

    async def _boom(song, task_id=None):
        from downloadkit.exceptions import CancelException
        raise CancelException("下载已取消")

    monkeypatch.setattr(server, "download_song", _boom)

    r = await server.api_playlist_batch_download(
        server.PlaylistBatchDownloadRequest(url="u", batch_size=2)
    )
    tid = r["task_id"]

    await server.api_playlist_batch_cancel(tid)
    assert d[tid]["status"] == "cancelled"

    # 模拟"在跑的曲稍后收尾"：download_func 抛 CancelException 走 finally
    t = q.active_tasks[f"{tid}_s0"]
    with pytest.raises(Exception):
        await t.download_func(t)

    assert d[tid]["status"] == "cancelled", \
        "收尾把 cancelled 覆盖掉了——前端进度会在两个终态间闪跳"
    # lane 必须已释放（cancel 端点或收尾各做一次，幂等）
    assert f"batch:{tid}" not in q.lane_sizes


@pytest.mark.asyncio
async def test_batch_cancel_unknown_404(batch_env):
    from fastapi import HTTPException
    server, _q, _d, _u = batch_env
    with pytest.raises(HTTPException) as ei:
        await server.api_playlist_batch_cancel("nope")
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_batch_cancel_wrong_type_400(batch_env):
    from fastapi import HTTPException
    server, _q, d, _u = batch_env
    d["other"] = {"type": "video_batch"}
    with pytest.raises(HTTPException) as ei:
        await server.api_playlist_batch_cancel("other")
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_batch_cancel_idempotent(batch_env, monkeypatch):
    """已终结的批再点停止：不重复取消，如实返回当前状态"""
    server, q, d, use_playlist = batch_env
    use_playlist(1)

    async def _none(song, task_id=None):
        return None

    monkeypatch.setattr(server, "download_song", _none)
    r = await server.api_playlist_batch_download(
        server.PlaylistBatchDownloadRequest(url="u", batch_size=1)
    )
    tid = r["task_id"]
    t = q.active_tasks[f"{tid}_s0"]
    await t.download_func(t)
    assert d[tid]["status"] == "done"

    res = await server.api_playlist_batch_cancel(tid)
    assert res["already_final"] is True
    assert res["status"] == "done"
    assert d[tid]["status"] == "done", "对已终结批的取消请求不许改状态"


# ---------------- P0-1 / P0-3 前端接线（静态钉死） ----------------

from pathlib import Path  # noqa: E402

_STATIC = Path(__file__).resolve().parent.parent / "downloadkit" / "static"
_MUSIC_JS = (_STATIC / "js" / "music.js").read_text(encoding="utf-8")
_UTILS_JS = (_STATIC / "js" / "utils.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")


def test_ui_has_batch_cancel_button():
    """P0-1：进度条区块必须有「停止下载」按钮，且接了取消端点"""
    assert 'id="pl-batch-cancel"' in _HTML, "缺停止下载按钮"
    assert "/api/playlist/batch/' + bt.task_id + '/cancel'" in _MUSIC_JS, \
        "music.js 没调批取消端点"
    assert "pl-batch-cancel" in _MUSIC_JS, "按钮没接线"


def test_ui_batch_cancel_wired_with_guard():
    """停止按钮要防重复点击（cancelling 标志）+ 走 uiConfirm 二次确认"""
    assert "bt.cancelling" in _MUSIC_JS, "缺防重复点击标志"
    assert "uiConfirm(" in _MUSIC_JS, "停止前没有确认弹窗"


def test_api_carries_http_status_on_error():
    """P0-3：api() 失败要把 HTTP 状态码挂到 err.status 上"""
    assert "err.status = r.status" in _UTILS_JS, "api() 没携带状态码"


def test_poll_stops_on_missing_task():
    """P0-3：轮询对 404/400 必须止损（不再无限重试）"""
    assert "err.status === 404" in _MUSIC_JS or "(err.status === 404" in _MUSIC_JS, \
        "pollBatchProgress 没对 404 止损"
    assert "err.status === 400" in _MUSIC_JS, "pollBatchProgress 没对 400 止损"


