"""CLI entry -- click commands + rich console output."""

import sys
import os

# Fix Windows console encoding for Unicode (e.g. Douyin titles with special chars)
if sys.platform == "win32":
    os.system("")  # enable VT sequences
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pathlib import Path
_vendor = Path(__file__).parent.parent / "_vendor"
if _vendor.exists():
    sys.path.insert(0, str(_vendor))

import asyncio
import json
import logging
import urllib.parse
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.markup import escape
from rich import print as rprint

from urllib.parse import urlencode

from .searcher import search_all
from .playlist import parse_playlist
from .downloader import download_song, download_batch
from .bookmarks import flatten_bookmarks
from .utils import DEFAULT_CONFIG
from .douyin import fetch as douyin_fetch, fetch_content, parse_url, download_content, ContentType

console = Console()
logging.basicConfig(level=logging.WARNING)


def _quiet_logs(level: int = logging.WARNING):
    """压低 downloadkit 日志级别，保证 CLI 输出（尤其 --json）不被污染。

    downloadkit/logger.py 在 import 时给 "downloadkit" logger 挂了
    stdout handler（INFO 级）——server 服务端这样正合适，但 CLI 的
    stdout 是给用户/管道看的：INFO 日志会盖过 rich 界面，--json 时
    更会直接把 JSON 挤成非法文本。
    """
    lg = logging.getLogger("downloadkit")
    lg.setLevel(level)
    for h in lg.handlers:
        h.setLevel(level)


def run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)


@click.group()
@click.version_option(version="0.5.0", prog_name="downloadkit")
@click.option("-v", "--verbose", is_flag=True,
              help="显示详细日志（默认已压掉 INFO，保持界面干净）")
@click.option("--server", default=None, envvar="DOWNLOADKIT_SERVER",
              help="服务地址，queue 等远程命令用（默认 http://127.0.0.1:8765，"
                   "也可用环境变量 DOWNLOADKIT_SERVER）")
def main(verbose: bool, server: str | None):
    """downloadkit -- Multi-platform resource downloader.

    \b
    Music:    search / playlist / download（QQ音乐、网易云、酷我、咪咕…）
    Video:    parse（只解析）/ video（解析+下载，支持抖音、B站、YouTube、
              小红书、以及任意网页/直链的 generic 兜底）
    Douyin:   douyin（支持分享文本）
    Queue:    queue（列任务/暂停/重试/移除，需服务在跑）
    """
    _quiet_logs(logging.INFO if verbose else logging.WARNING)
    if server:
        global _SERVER
        _SERVER = server.rstrip("/")


@main.command()
@click.argument("keyword")
@click.option("-n", "--count", default=20, show_default=True, help="Number of results")
@click.option("-s", "--select", "sel", type=str, default=None, help="Select by number (e.g. 16 or 1,3,5 or 1-3)")
def search(keyword: str, count: int, sel: str):
    """Search songs across multiple platforms."""
    console.print(f"[bold]Searching:[/bold] [cyan]{keyword}[/cyan]")

    songs = run_async(search_all(keyword, limit=count))

    if not songs:
        console.print("[red]No songs found.[/red]")
        return

    table = Table(title=f"Results: {keyword}", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="cyan", width=30)
    table.add_column("Artist", style="green", width=20)
    table.add_column("Album", style="yellow", width=20)
    table.add_column("Platform", style="blue", width=10)

    for i, s in enumerate(songs, 1):
        table.add_row(
            str(i),
            s.title[:28] + ".." if len(s.title) > 30 else s.title,
            s.artist[:18] + ".." if len(s.artist) > 20 else s.artist,
            s.album[:18] + ".." if len(s.album) > 20 else s.album,
            s.platform.upper(),
        )

    console.print(table)

    if sel:
        selected = _parse_selection(sel, songs)
    else:
        choice = click.prompt(
            "Enter number(s) to download (comma-separated, a=all, q=quit)",
            default="q",
            show_default=False,
        )
        if choice.lower() == "q":
            return
        selected = _parse_selection(choice, songs)

    if not selected:
        console.print("[yellow]No songs selected.[/yellow]")
        return

    _download_selected(selected)


@main.command()
@click.argument("url")
def playlist(url: str):
    """Import a playlist and batch download (QQ Music / NetEase)."""
    with console.status("[bold]Parsing playlist...[/bold]"):
        try:
            pl = run_async(parse_playlist(url))
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return

    console.print(Panel.fit(
        f"[bold cyan]{pl.name}[/bold cyan]\n"
        f"Platform: {pl.platform}  |  Tracks: {pl.song_count}\n"
        f"{pl.description[:100] if pl.description else ''}",
        title="Playlist Info",
    ))

    if not pl.songs:
        console.print("[yellow]Playlist is empty.[/yellow]")
        return

    if not click.confirm("Download all songs?"):
        return

    console.print(f"\n[bold]Downloading {len(pl.songs)} songs...[/bold]\n")

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("*"),
        TextColumn("{task.completed}/{task.total}"),
    ) as progress:
        overall = progress.add_task("[cyan]Overall", total=len(pl.songs))
        success, failed = 0, 0
        for i, song in enumerate(pl.songs):
            task = progress.add_task(f"[dim]{song.title[:30]}", total=100)
            result = run_async(download_song(song, progress=None))
            progress.update(task, completed=100, visible=False)
            progress.update(overall, advance=1,
                          description=f"[cyan]Overall ({i+1}/{len(pl.songs)})")
            if result:
                success += 1
            else:
                failed += 1

    console.print(f"\n[bold green]Done![/bold green] Success [green]{success}[/green], Failed [red]{failed}[/red]")


@main.command()
@click.argument("identifier")
def download(identifier: str):
    """Download a song directly by URL or ID."""
    if "://" not in identifier:
        console.print("[yellow]Please provide a song link or use the search command.[/yellow]")
        return

    from .playlist import parse_playlist
    try:
        pl = run_async(parse_playlist(identifier))
        if len(pl.songs) == 1:
            song = pl.songs[0]
        else:
            console.print(f"[yellow]This is a playlist ({len(pl.songs)} tracks), use the playlist command.[/yellow]")
            return
    except Exception:
        console.print("[red]Unable to parse this link.[/red]")
        return

    console.print(f"[bold]Downloading:[/bold] {song.title} - {song.artist}")
    with console.status("[bold]Downloading..."):
        result = run_async(download_song(song))
    if result:
        console.print(f"[green]Saved to:[/green] {result}")
    else:
        console.print("[red]Download failed[/red]")


@main.command()
@click.argument("input_text")
@click.option("-o", "--output", default=None,
              help="输出根目录（产物落在 <目录>/{videos,images,animated}/；"
                   "不指定则用设置里的下载分类目录）")
def douyin(input_text: str, output: str | None):
    """Parse a Douyin link or share text and download watermark-free content.

    Supports video, image, and animated content.
    Supports both short links (https://v.douyin.com/xxx/) and full share text.
    """
    url = parse_url(input_text)
    if not url:
        console.print("[red]未在输入中找到抖音链接[/red]")
        return

    console.print(f"[bold]解析抖音链接:[/bold] [cyan]{url}[/cyan]")

    # Step 1: fetch content
    with console.status("[bold]获取内容信息..."):
        try:
            content = run_async(fetch_content(input_text))
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return

    # Display info based on content type
    type_label = "视频" if content.content_type == ContentType.VIDEO else \
                "图文" if content.content_type == ContentType.IMAGE else "动图"
    
    content_info = f"[bold]{content.title}[/bold]\n" \
                   f"[dim]作者:[/dim] {content.author or '未知'}  |  [dim]ID:[/dim] {content.item_id}  |  [dim]类型:[/dim] {type_label}"
    
    if content.content_type == ContentType.IMAGE:
        content_info += f"\n[dim]图片数量:[/dim] {len(content.images)}"
    
    console.print(Panel.fit(content_info, title="抖音内容"))

    # Step 2: download
    console.print(f"\n[bold]下载中...[/bold]")
    with console.status(f"[bold]下载{type_label}..."):
        try:
            paths = run_async(download_content(content, output))
        except ValueError as e:
            console.print(f"[red]下载失败: {e}[/red]")
            return

    if len(paths) == 1:
        path = paths[0]
        size = path.stat().st_size
        human = f"{size / 1048576:.1f} MB" if size > 1048576 else f"{size / 1024:.1f} KB"
        console.print(f"\n[bold green]Done![/bold green] Saved to [green]{path}[/green] ({human})")
    else:
        total_size = sum(p.stat().st_size for p in paths)
        human = f"{total_size / 1048576:.1f} MB" if total_size > 1048576 else f"{total_size / 1024:.1f} KB"
        # output 可能是 None（未指定 -o），此时用产物实际所在目录
        dest = output if output else str(Path(paths[0]).parent)
        console.print(f"\n[bold green]Done![/bold green] Saved {len(paths)} files to [green]{dest}[/green] ({human})")
        for i, p in enumerate(paths, 1):
            size = p.stat().st_size
            s = f"{size / 1024:.1f} KB" if size < 1048576 else f"{size / 1048576:.1f} MB"
            console.print(f"  {i}. [green]{p.name}[/green] ({s})")


@main.command()
@click.argument("url")
@click.option("-e", "--episodes", is_flag=True,
              help="展开选集（合集/播放列表类链接），不解析单集")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（管道/脚本友好）")
@click.option("--referer", default="",
              help="来源页 Referer（generic 防盗链：嗅探拿到的真实来源页）")
@click.option("--name", "name_hint", default="",
              help="命名提示（书签标题等，参与文件名推导 suggested_name）")
def parse(url: str, episodes: bool, as_json: bool, referer: str, name_hint: str):
    """解析视频链接（抖音/B站/YouTube/小红书/通用网页），只看不下载。

    \b
    Examples:
      downloadkit parse "https://www.bilibili.com/video/BV1xx411c7mD"
      downloadkit parse "https://v.douyin.com/xxx/" --json
      downloadkit parse "https://example.com/play/1" --episodes
    """
    from .video_service import detect_platform, parse_url as video_parse_url

    if as_json:
        # --json 面向管道：stdout 必须只有 JSON，日志一律不许出现
        _quiet_logs(logging.ERROR)

    platform = detect_platform(url)
    if not platform:
        console.print("[red]不支持的平台链接[/red]")
        return

    if episodes:
        from .episodes import expand_episodes
        with console.status(f"[bold]展开选集（{platform}）..."):
            try:
                # generic 影视站 yt-dlp generic extractor 几乎必失败，
                # 跳过省 20s 白跑（与 /api/video/episodes 同参）
                r = run_async(expand_episodes(
                    url, timeout=60.0,
                    try_ytdlp=(platform != 'generic'),
                    use_browser=True,
                ))
            except Exception as e:
                console.print(f"[red]展开选集失败: {e}[/red]")
                return
        if as_json:
            click.echo(json.dumps(r, ensure_ascii=False, indent=2))
            return
        _render_episodes(r)
        return

    with console.status(f"[bold]解析 {platform}..."):
        try:
            info = run_async(video_parse_url(
                url, referer=referer, title_hint=name_hint))
        except Exception as e:
            console.print(f"[red]解析失败: {e}[/red]")
            return

    if as_json:
        click.echo(json.dumps(_public_info(info), ensure_ascii=False, indent=2))
        return
    _render_parse(info)


@main.command()
@click.argument("url")
@click.option("-o", "--output", default=None,
              help="输出根目录（抖音会再建 videos/images/animated 分类子目录，"
                   "其余平台直接落该目录；不指定则用设置里的下载目录）")
@click.option("-q", "--quality", default="best", show_default=True,
              type=click.Choice(["best", "1080", "720", "480", "360"],
                                case_sensitive=False),
              help="画质（YouTube/generic 生效）")
@click.option("-e", "--episodes", is_flag=True, help="展开选集并批量下载")
@click.option("-n", "--select", "sel", default=None,
              help="选集选择（配合 -e：如 3 或 1,3 或 1-5 或 a=全部）")
@click.option("--referer", default="", help="来源页 Referer（generic 防盗链）")
@click.option("--name", "name_hint", default="", help="命名提示（决定产物文件名）")
def video(url: str, output: str | None, quality: str, episodes: bool,
          sel: str | None, referer: str, name_hint: str):
    """解析并下载视频（抖音/B站/YouTube/小红书/通用网页与直链）。

    \b
    Examples:
      downloadkit video "https://www.bilibili.com/video/BV1xx411c7mD"
      downloadkit video "https://example.com/v.m3u8" -q 720
      downloadkit video "https://example.com/play/1" -e            # 全部选集
      downloadkit video "https://example.com/play/1" -e -n 1-5     # 只下前 5 集
    """
    from .video_service import (
        detect_platform, parse_url as video_parse_url, download_parsed)

    platform = detect_platform(url)
    if not platform:
        console.print("[red]不支持的平台链接[/red]")
        return

    # 收集待下载目标：默认单条；-e 时展开选集后按选择填入
    targets: list[dict] = [{"url": url, "label": name_hint}]
    if episodes:
        from .episodes import expand_episodes
        with console.status(f"[bold]展开选集（{platform}）..."):
            try:
                r = run_async(expand_episodes(
                    url, timeout=60.0,
                    try_ytdlp=(platform != 'generic'),
                    use_browser=True,
                ))
            except Exception as e:
                console.print(f"[red]展开选集失败: {e}[/red]")
                return
        if not r.get("count"):
            console.print(f"[red]未找到选集: {r.get('error') or '无结果'}[/red]")
            return
        groups = r.get("groups", [])
        g = groups[0]  # expand_episodes 已按 count 降序，取最大组
        if len(groups) > 1:
            console.print(f"[yellow]发现 {len(groups)} 组选集，"
                          f"使用最大组（{g.get('count')} 集）[/yellow]")
        items = g.get("items", [])
        console.print(f"[bold]{r.get('title') or url}[/bold] —— 共 {len(items)} 集")
        if sel:
            picked = _pick_indexes(sel, len(items))
        else:
            choice = click.prompt(
                "选择要下载的集（如 1-5 / 1,3 / a=全部 / q=退出）", default="a")
            if choice.strip().lower() == "q":
                return
            picked = _pick_indexes(choice, len(items))
        if not picked:
            console.print("[yellow]未选择任何集[/yellow]")
            return
        targets = [{"url": items[i]["url"], "label": items[i].get("label", "")}
                   for i in picked]

    total = len(targets)
    ok, failed = 0, 0
    for idx, t in enumerate(targets, 1):
        head = f"[{idx}/{total}] " if total > 1 else ""
        with console.status(f"{head}解析 {t['url'][:60]}..."):
            try:
                info = run_async(video_parse_url(
                    t["url"], referer=referer,
                    title_hint=t["label"] or name_hint))
            except Exception as e:
                console.print(f"[red]{head}解析失败: {e}[/red]")
                failed += 1
                continue
        title = (info.get("title") or t["label"] or t["url"])[:46]
        console.print(f"{head}[cyan]{title}[/cyan]")
        with console.status(f"{head}下载中..."):
            try:
                paths = run_async(download_parsed(
                    info, out_dir=output, quality=quality.lower(),
                    name_hint=t["label"] or name_hint, referer=referer))
            except Exception as e:
                console.print(f"[red]{head}下载失败: {e}[/red]")
                failed += 1
                continue
        ok += 1
        _render_done(paths)

    if total > 1:
        console.print(f"\n[bold green]Done![/bold green] 成功 [green]{ok}[/green]，"
                      f"失败 [red]{failed}[/red]")


# ────────────────────────────── 队列（连运行中的服务） ──────────────────────────────
# 队列状态是服务进程的内存态（download_queue.active_tasks + server._downloads），
# CLI 直连模块只会看到一份空队列，必须走 HTTP 读写正在运行的服务。

_SERVER = "http://127.0.0.1:8765"

_STATUS_LABEL = {
    "pending": "等待中",
    "downloading": "下载中",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}
_STATE_GROUP = {
    "active": ("pending", "downloading", "paused"),
    "done": ("completed",),
    "failed": ("failed",),
}
_STATE_LABEL = {"all": "全部", "active": "进行中", "done": "已完成", "failed": "失败"}


def _queue_api(method: str, path: str, body=None, timeout: float = 30.0):
    """调运行中服务的 API，返回 (状态码, 数据)。

    queue 和 subscribe 两组命令共用这一层：它们要的东西（队列在服务进程
    内存里、订阅要抓主页得用服务进程那份浏览器）CLI 直连模块都拿不到，
    只能问正在跑的服务。名字沿用 _queue_api 是因为 P5-2 先落的它。

    连不上（服务没跑/端口不对）返回 (0, 中文提示)；非 2xx 时数据是
    服务端的 {"detail": "..."} 或 {"ok": false, "error": "..."}，
    由 _queue_fail 统一取出展示。

    timeout 默认 30 秒够队列用；抓主页的检查命令（check/check-all）要
    逐个开页面滚动，远超 30 秒，得由调用方传更长的值——否则服务端还在
    正常干活，客户端先报超时了。
    """
    import httpx
    url = f"{_SERVER.rstrip('/')}{path}"
    try:
        resp = httpx.request(method, url, json=body, timeout=timeout)
    except httpx.HTTPError as e:
        return 0, (f"连不上服务 {_SERVER}（{e.__class__.__name__}）。"
                    "这个命令需要 DownloadKit 正在运行，换地址用 --server 指定。")
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text


def _detail_of(data) -> str:
    """从服务端响应里取出可读的错误描述，退化为整段 JSON。

    服务端两种错误写法都得认：HTTPException 是 {"detail": "..."}，
    而 401/429 那类业务状态（没登录、撞风控）是 {"ok": false, "error": "..."}。
    只认 detail 的话，未登录会被原样吐成一坨 JSON。
    """
    if isinstance(data, dict):
        for key in ("detail", "error", "message"):
            if data.get(key):
                return str(data[key])
        return json.dumps(data, ensure_ascii=False)
    return str(data)


def _queue_fail(code: int, data) -> None:
    if code == 0:
        console.print(f"[red]{data}[/red]")  # 网络错误：data 是提示文本
        return
    console.print(f"[red]失败（HTTP {code}）: {_detail_of(data)}[/red]")


def _task_progress(t: dict) -> str:
    try:
        return f"{float(t.get('progress') or 0) * 100:.0f}%"
    except (TypeError, ValueError):
        return "-"


@main.group()
def queue():
    """下载队列管理（需要 DownloadKit 正在运行，直连它的 Web 服务）。

    \b
    Examples:
      downloadkit queue list
      downloadkit queue list failed --json
      downloadkit queue retry-failed
      downloadkit queue open <task_id>
    """
    pass


@queue.command("list")
@click.argument("state", default="all",
                type=click.Choice(["all", "active", "done", "failed"]))
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（管道/脚本友好）")
def queue_list(state: str, as_json: bool):
    """列出队列任务。

    STATE 取 all（默认）/ active（等待中+下载中+已暂停）/ done（已完成）/
    failed（失败）；已取消的任务只在 all 里出现。
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    code, data = _queue_api("GET", "/api/queue/status")
    if code != 200:
        if as_json:
            # 管道侧也要结构化错误（含 HTTP 码），别只吐半截文本
            click.echo(json.dumps(
                {"error": f"HTTP {code}: {_detail_of(data)}" if code else str(data)},
                ensure_ascii=False))
        else:
            _queue_fail(code, data)
        return

    tasks = list(data.get("tasks") or []) if isinstance(data, dict) else []
    if state != "all":
        tasks = [t for t in tasks if t.get("status") in _STATE_GROUP[state]]

    if as_json:
        click.echo(json.dumps(tasks, ensure_ascii=False, indent=2))
        return

    if not tasks:
        console.print(f"[yellow]没有{_STATE_LABEL[state]}的任务[/yellow]")
        return

    table = Table(title=f"下载队列 · {_STATE_LABEL[state]}（{len(tasks)} 条）",
                  header_style="bold magenta")
    # Task ID 必须 no_wrap 全长可见：截断了用户就没法把 id 复制给
    # pause/retry/open 用（实测 80 列终端会把 40 字符 id 压没）。
    # 错误列因此砍掉，失败原因挪到表格下方整行打印。
    table.add_column("Task ID", style="dim", no_wrap=True)
    table.add_column("标题", max_width=20)
    table.add_column("状态")
    table.add_column("进度", justify="right")

    errors: list[tuple[str, str]] = []
    for t in tasks:
        st = t.get("status", "?")
        label = _STATUS_LABEL.get(st, st)
        if st == "failed":
            label = f"[red]{label}[/red]"
        elif st == "completed":
            label = f"[green]{label}[/green]"
        err = (t.get("error") or "").strip()
        if st == "failed" and err:
            errors.append((str(t.get("task_id", "")), err))
        table.add_row(
            str(t.get("task_id", "")),
            (t.get("title") or t.get("filename") or ""),
            label,
            _task_progress(t),
        )
    console.print(table)

    if errors:
        console.print("[red]失败原因:[/red]")
        for tid, err in errors:
            console.print(f"  [dim]{tid}[/dim] → {err}")

    if state == "all" and isinstance(data, dict):
        console.print(
            f"下载中 {data.get('downloading', 0)} · 等待 {data.get('pending', 0)}"
            f" · 完成 {data.get('completed', 0)} · 失败 {data.get('failed', 0)}")


def _queue_action(path: str, ok_msg: str) -> dict | None:
    """POST 一个队列动作端点：成功打印确认，失败打印服务端 detail。"""
    code, data = _queue_api("POST", path)
    if code != 200:
        _queue_fail(code, data)
        return None
    console.print(f"[bold green]✓[/bold green] {ok_msg}")
    return data if isinstance(data, dict) else {}


def _require_task(task_id: str) -> bool:
    """pause/resume/cancel 前确认任务在队列里。

    这三个端点是 fire-and-forget：DownloadQueue 只记标志位，任务不在也回 200，
    于是「暂停一个不存在的任务」会报成功。先查一次队列，别给用户假成功。
    """
    code, data = _queue_api("GET", "/api/queue/status")
    if code != 200:
        _queue_fail(code, data)
        return False
    tasks = list((data.get("tasks") or [])) if isinstance(data, dict) else []
    if any(t.get("task_id") == task_id for t in tasks):
        return True
    console.print(f"[red]队列里没有任务 {task_id}（用 queue list 看任务号）[/red]")
    return False


@queue.command("pause")
@click.argument("task_id")
def queue_pause(task_id: str):
    """暂停一个任务（批量任务在条目边界生效）。"""
    if _require_task(task_id):
        _queue_action(f"/api/queue/{task_id}/pause", f"已暂停 {task_id}")


@queue.command("resume")
@click.argument("task_id")
def queue_resume(task_id: str):
    """恢复一个已暂停的任务。"""
    if _require_task(task_id):
        _queue_action(f"/api/queue/{task_id}/resume", f"已恢复 {task_id}")


@queue.command("cancel")
@click.argument("task_id")
def queue_cancel(task_id: str):
    """取消一个任务。"""
    if _require_task(task_id):
        _queue_action(f"/api/queue/{task_id}/cancel", f"已取消 {task_id}")


@queue.command("retry")
@click.argument("task_id")
def queue_retry(task_id: str):
    """重试一个失败任务（断点续传接着下，不清进度）。"""
    data = _queue_action(f"/api/queue/{task_id}/retry", f"已重新入队 {task_id}")
    if data and data.get("new_task_id"):
        console.print(f"[dim]重新创建的任务号: {data['new_task_id']}[/dim]")


@queue.command("retry-failed")
def queue_retry_failed():
    """一键重试队列里全部失败任务。"""
    code, data = _queue_api("POST", "/api/queue/retry-failed")
    if code != 200:
        _queue_fail(code, data)
        return
    retried = data.get("retried", 0) if isinstance(data, dict) else 0
    orphaned = data.get("orphaned", 0) if isinstance(data, dict) else 0
    console.print(f"[bold green]✓[/bold green] 已重新入队 [green]{retried}[/green] 个失败任务")
    if orphaned:
        console.print(f"[yellow]{orphaned} 个失败记录已过期无法重试"
                      f"（原任务已被清理出队列）[/yellow]")


@queue.command("rm")
@click.argument("task_id")
def queue_rm(task_id: str):
    """把已结束的任务移出列表（进行中/已暂停的任务会被服务端拒绝）。"""
    _queue_action(f"/api/queue/{task_id}/dismiss", f"已移除 {task_id}")


@queue.command("open")
@click.argument("task_id")
@click.option("--path", "path_", default=None,
              help="直接给文件路径或裸文件名（不给则按任务记录的文件名在下载目录里找）")
def queue_open(task_id: str, path_: str | None):
    """打开任务产物文件，成功后把该任务移出列表（对齐界面「点完成行」）。"""
    target = path_
    if not target:
        code, data = _queue_api("GET", "/api/queue/status")
        if code != 200:
            _queue_fail(code, data)
            return
        tasks = list((data.get("tasks") or [])) if isinstance(data, dict) else []
        t = next((x for x in tasks if x.get("task_id") == task_id), None)
        if t is None:
            console.print(f"[red]队列里没有任务 {task_id}（用 queue list 看任务号）[/red]")
            return
        target = t.get("filename") or ""
        if not target:
            console.print(f"[red]任务 {task_id} 没记录文件名，用 --path 指定文件[/red]")
            return

    code, data = _queue_api("POST", "/api/open-file", {"path": target})
    if code != 200:
        _queue_fail(code, data)
        return
    opened = data.get("path") if isinstance(data, dict) else None
    console.print(f"[bold green]✓[/bold green] 已打开 [green]{opened or target}[/green]")

    # 打开成功才移除；失败留在列表里（对齐界面行为）
    code, data = _queue_api("POST", f"/api/queue/{task_id}/dismiss")
    if code == 200:
        console.print(f"[dim]已把 {task_id} 移出队列列表[/dim]")
    elif code:  # 0 是网络错误（刚连上过，一般不会出现），409 是任务还在跑
        _queue_fail(code, data)


# ==================================================================
# 订阅管理（P5-3）
# ==================================================================
# 和 queue 同一批理由走 HTTP：订阅要抓主页，用的是服务进程里那份浏览器
# （douyin._browser_instance），CLI 自己再起一份就是另一套登录态，还会跟
# 轮询抢同一个 Chromium；检查完要入队，队列又是服务进程的内存态。所以
# 整组命令一律问正在跑的服务，绝不直连模块。
#
# ⚠ check / check-all 会真抓抖音主页：串行、慢、且有风控。短链
#   （v.douyin.com）限流实测约 1 分钟 1~2 次，能贴主页链接就贴主页链接。

# 抓主页的调用（add / check / check-all）要开页面、滚动、逐个创作者串行跑，
# 远超传输层默认的 30 秒——服务端还在正常干活，客户端先报超时了。
_API_TIMEOUT_LONG = 600.0


def _ago(ts) -> str:
    """时间戳 → “3 分钟前”；空值或解析不出返回 '-'（= 还没检查过）。"""
    if not ts:
        return "-"
    try:
        dt = datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(ts)
    s = (datetime.now() - dt).total_seconds()
    if s < 0:
        return "刚刚"
    if s < 60:
        return f"{int(s)} 秒前"
    if s < 3600:
        return f"{int(s // 60)} 分钟前"
    if s < 86400:
        return f"{int(s // 3600)} 小时前"
    return f"{int(s // 86400)} 天前"


_SCOPE_TOKENS = {
    "only_new": "only_new", "new": "only_new",
    "backfill_n": "backfill_n", "backfill": "backfill_n",
    "all": "all",
}


def _map_scope(token: str) -> str | None:
    """把命令行写的范围词翻成服务端认的取值；认不出返回 None。

    接受 new / backfill 这种短写：只下新作品才是常用档，没谁天天敲
    only_new。真正的取值校验仍在服务端（validate_scope），这里只做翻译。
    """
    return _SCOPE_TOKENS.get((token or "").strip().lower())


def _scope_text(scope, param="") -> str:
    """范围取值 → 一句人话（列表/确认提示共用）。"""
    scope = (scope or "").strip()
    if scope == "only_new":
        return "只下新作品"
    if scope == "backfill_n":
        return f"新 + 往回补 {param or '?'} 个"
    if scope == "all":
        return "全部历史作品"
    return scope or "-"


def _fetch_creators(quiet: bool = False) -> list[dict] | None:
    """GET /api/subscriptions；失败打印原因并返回 None。

    quiet=True 给「失败了还会自己再报一次错」的场景用（比如 add 的前置查重），
    免得同一次连不上吐两条重复提示。
    """
    code, data = _queue_api("GET", "/api/subscriptions")
    if code != 200:
        if not quiet:
            _queue_fail(code, data)
        return None
    if not isinstance(data, dict):
        console.print(f"[red]服务返回了看不懂的内容：{data}[/red]")
        return None
    return list(data.get("creators") or [])


def _print_candidates(creators: list[dict], limit: int = 30):
    """列出可选创作者，让用户能直接复制昵称（没匹配上时的兜底提示）。"""
    if not creators:
        console.print("[dim]（还没有任何订阅，先 subscribe add <主页链接>）[/dim]")
        return
    names = [(_c.get("nickname") or "").strip() or f"…{_c.get('sec_uid', '')[-8:]}"
             for _c in creators[:limit]]
    console.print(f"[dim]可用：{'、'.join(names)}" +
                  (f"…（共 {len(creators)} 个）" if len(creators) > limit else "") +
                  "[/dim]")


def _resolve_creator(sel: str, creators: list[dict]) -> str | None:
    """把用户输入（昵称或 sec_uid）解析成 sec_uid，认不出返回 None。

    sec_uid 长得像 MS4wLjABAAAA…（40+ 字符），没人会背它——用户手上只有
    昵称。所以按「昵称精确 → 唯一前缀 → 唯一子串」三层认；多义或没命中就
    把候选列出来，绝不猜一个发出去。
    """
    sel = (sel or "").strip()
    if not sel:
        console.print("[red]请输入创作者昵称或 sec_uid[/red]")
        return None

    def nick(c):
        return (c.get("nickname") or "").strip()

    for pick in (
        [c for c in creators if nick(c) == sel],
        [c for c in creators if nick(c) and nick(c).startswith(sel)],
        [c for c in creators if sel in nick(c)],
    ):
        if len(pick) == 1:
            return pick[0].get("sec_uid")
        if len(pick) > 1:
            console.print(f"[red]{sel!r} 匹配到 {len(pick)} 个创作者，说得再具体点：[/red]")
            for c in pick:
                console.print(f"  [dim]{c.get('sec_uid')}[/dim]  {nick(c)}")
            return None

    # 昵称三层都没命中，试试它本身是不是 sec_uid（直接粘 ID 的用户）
    if any(c.get("sec_uid") == sel for c in creators):
        return sel

    console.print(f"[red]没有匹配的创作者 {sel!r}[/red]")
    _print_candidates(creators)
    return None


def _fail_browser(code: int, data) -> None:
    """401/429 这类「抖音侧」状态给下一步动作，而不是把原文甩给用户。

    服务端这两类是 JSONResponse({"ok": false, "error": ...})，不是
    HTTPException 的 detail —— _detail_of 两种都认，这里再补行动建议。
    """
    if code == 401:
        console.print(f"[red]{_detail_of(data)}[/red]")
        console.print("[dim]→ 启动程序 → 设置 → 登录抖音，再重试。[/dim]")
    elif code == 429:
        console.print(f"[red]{_detail_of(data)}[/red]")
        console.print("[dim]→ 短链限流很严（约 1 分钟 1~2 次）：改贴主页链接，或等几分钟再试。[/dim]")
    else:
        _queue_fail(code, data)


def _confirm_all(action: str, yes: bool) -> bool:
    """范围是「全部历史作品」时先确认——500 作品的创作者会一次全入队。"""
    if yes:
        return True
    try:
        click.confirm(
            f"{action}用的是「全部历史作品」范围，可能一次入队成百上千个任务，继续？",
            abort=True)
    except click.Abort:
        console.print("[yellow]已取消[/yellow]")
        return False
    return True


@main.group()
def subscribe():
    """创作者订阅管理（需要 DownloadKit 正在运行，抓主页用它的浏览器）。

    \b
    Examples:
      downloadkit subscribe add https://www.douyin.com/user/MS4wLj...
      downloadkit subscribe list
      downloadkit subscribe scope 某博主 backfill 5
      downloadkit subscribe check 某博主
      downloadkit subscribe check-all
      downloadkit subscribe remove 某博主
    """
    pass


@subscribe.command("list")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（管道/脚本友好）")
def subscribe_list(as_json: bool):
    """列出全部订阅的创作者 + 总览统计。"""
    if as_json:
        _quiet_logs(logging.ERROR)

    code, data = _queue_api("GET", "/api/subscriptions")
    if code != 200:
        if as_json:
            click.echo(json.dumps(
                {"error": f"HTTP {code}: {_detail_of(data)}" if code else str(data)},
                ensure_ascii=False))
        else:
            _queue_fail(code, data)
        return

    if not isinstance(data, dict):
        _queue_fail(code, data)
        return

    creators = list(data.get("creators") or [])
    if as_json:
        click.echo(json.dumps(creators, ensure_ascii=False, indent=2))
        return

    if not creators:
        console.print("[yellow]还没有订阅任何创作者[/yellow]")
        console.print("[dim]先 subscribe add <主页链接>；短链限流严，优先贴主页链接。[/dim]")
        return

    table = Table(title=f"订阅创作者（{len(creators)} 个）",
                  header_style="bold magenta")
    table.add_column("昵称", max_width=16, no_wrap=True)
    table.add_column("状态")
    table.add_column("下载范围", max_width=16)
    table.add_column("上次检查", style="dim")
    table.add_column("作品", justify="right")

    done: list[tuple[str, str]] = []
    for c in creators:
        name = ((c.get("nickname") or "").strip()
                or f"…{str(c.get('sec_uid') or '')[-8:]}")
        enabled = c.get("enabled", 1)
        state = ("[green]启用[/green]" if enabled
                 else "[yellow]已暂停[/yellow]")
        table.add_row(
            escape(name), state,
            _scope_text(c.get("download_scope"), c.get("scope_param")),
            _ago(c.get("last_checked")),
            str(c.get("works_count", 0)),
        )
        res = (c.get("last_result") or "").strip()
        if res:
            done.append((name, res))
    console.print(table)

    if done:
        # 状态句（可能很长）不进表格：塞进去会在 80 列终端里被折成两三行，
        # 反而看不清谁是谁——和 queue list 把失败原因挪到表格外同一套理由。
        console.print("[bold]上次结果[/bold]")
        for name, res in done:
            console.print(f"  [dim]{escape(name)}[/dim] → {res}")

    stats = data.get("stats") or {}
    console.print(
        f"订阅 {stats.get('creators', 0)} 个"
        f"（启用 {stats.get('enabled', 0)}）"
        f" · 已发现作品 {stats.get('works_seen', 0)}")
    if stats.get("db_path"):
        console.print(f"[dim]订阅库: {stats['db_path']}[/dim]")


@subscribe.command("add")
@click.argument("url")
@click.option("--no-profile", is_flag=True,
              help="不抓主页昵称头像，只存 ID（省一次页面加载，昵称得自己补）")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（管道/脚本友好）")
def subscribe_add(url: str, no_profile: bool, as_json: bool):
    """订阅一个创作者。主页链接 / 短链 / sec_uid / 带文案的分享内容都行。

    \b
    ⚠ 短链（v.douyin.com）限流实测约 1 分钟 1~2 次，能贴主页链接就贴主页链接。
      首次检查只建基线、一个都不下，之后才下载基线之后的新作品。
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    from .douyin_browser import extract_sec_uid

    # 能本地认出 sec_uid（纯正则，不联网）就先查一次，避免把
    # 「已经订阅过」当成新的成功报出去——服务端对重复订阅是原样返回记录，
    # 光看返回分辨不出是新增还是已存在。
    local_uid = extract_sec_uid((url or "").strip())
    if local_uid:
        known = _fetch_creators(quiet=True)
        if known is not None and any(
                c.get("sec_uid") == local_uid for c in known):
            console.print("[yellow]这个创作者已经订阅过了[/yellow]（"
                          "subscribe list 里就有，不会重复下老作品）")
            return

    code, data = _queue_api(
        "POST", "/api/subscriptions",
        {"url": url, "fetch_profile": not no_profile},
        timeout=_API_TIMEOUT_LONG)
    if code != 200:
        if as_json:
            click.echo(json.dumps(
                {"error": f"HTTP {code}: {_detail_of(data)}" if code else str(data)},
                ensure_ascii=False))
        else:
            _fail_browser(code, data)
        return

    rec = (data.get("creator") or {}) if isinstance(data, dict) else {}
    if as_json:
        click.echo(json.dumps(rec, ensure_ascii=False, indent=2))
        return

    name = ((rec.get("nickname") or "").strip()
            or f"…{str(rec.get('sec_uid') or '')[-8:]}")
    console.print(f"[bold green]✓[/bold green] 已订阅 [green]{escape(name)}[/green]")
    console.print(f"[dim]范围: {_scope_text(rec.get('download_scope'), rec.get('scope_param'))} · "
                  "首检只建基线不下载[/dim]")


@subscribe.command("remove")
@click.argument("creator")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（管道/脚本友好）")
def subscribe_remove(creator: str, as_json: bool):
    """取消订阅一个创作者。

    已发现的作品记录保留（seen_works 不清），所以取消后再加回来不会把
    老作品重新下一遍。
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    creators = _fetch_creators()
    if creators is None:
        return
    uid = _resolve_creator(creator, creators)
    if not uid:
        return

    code, data = _queue_api("DELETE", f"/api/subscriptions/{uid}")
    if code != 200:
        if as_json:
            click.echo(json.dumps(
                {"error": f"HTTP {code}: {_detail_of(data)}" if code else str(data)},
                ensure_ascii=False))
        else:
            _queue_fail(code, data)
        return

    name = ((creator or "").strip()
            if not creator.strip().startswith("MS4w") else f"…{uid[-8:]}")
    if as_json:
        click.echo(json.dumps({"ok": True, "sec_uid": uid}, ensure_ascii=False))
        return
    console.print(f"[bold green]✓[/bold green] 已取消订阅 [green]{escape(name)}[/green]"
                  f" [dim]（发现过的作品记录仍在）[/dim]")


# 订阅命令组的别名：queue 那组用 rm，两组写法统一省得记两套
subscribe.add_command(subscribe_remove, name="rm")


@subscribe.command("scope")
@click.argument("creator")
@click.argument("scope")
@click.argument("n", required=False, type=int)
@click.option("--yes", "-y", is_flag=True, help="跳过确认（范围 all 时用）")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（管道/脚本友好）")
def subscribe_scope(creator: str, scope: str, n: int | None,
                    yes: bool, as_json: bool):
    """设置某创作者的下载范围，改完下次检查生效（不会立刻开任务）。

    SCOPE 取 only_new（只下新作品）/ backfill_n（新作品 + 往回补 N 个）/
    all（全部历史作品），也接受短写 new / backfill / all。

    \b
    Examples:
      downloadkit subscribe scope 某博主 new
      downloadkit subscribe scope 某博主 backfill 5
      downloadkit subscribe scope 某博主 all --yes
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    mapped = _map_scope(scope)
    if not mapped:
        console.print(f"[red]下载范围只能是 only_new / backfill_n / all，收到 {scope!r}[/red]")
        return

    if mapped == "backfill_n":
        if n is None:
            console.print("[red]backfill_n 要给个数：subscribe scope 某博主 backfill 5[/red]")
            return
        if not (1 <= n <= 9999):
            console.print("[red]往回补的个数要在 1-9999 之间[/red]")
            return
        param = str(n)
    else:
        if n is not None:
            console.print(f"[red]{mapped} 不带个数，只有 backfill_n 才要 N[/red]")
            return
        param = ""

    creators = _fetch_creators()
    if creators is None:
        return
    uid = _resolve_creator(creator, creators)
    if not uid:
        return
    if mapped == "all" and not _confirm_all("这个创作者", yes):
        return

    code, data = _queue_api("POST", f"/api/subscriptions/{uid}/scope",
                            {"scope": mapped, "param": param})
    if code != 200:
        if as_json:
            click.echo(json.dumps(
                {"error": f"HTTP {code}: {_detail_of(data)}" if code else str(data)},
                ensure_ascii=False))
        else:
            _queue_fail(code, data)
        return

    rec = ((data.get("creator") or {}) if isinstance(data, dict) else {})
    if as_json:
        click.echo(json.dumps(rec, ensure_ascii=False, indent=2))
        return
    name = ((rec.get("nickname") or "").strip() or f"…{uid[-8:]}")
    console.print(f"[bold green]✓[/bold green] {escape(name)} 的下载范围 → "
                  f"[green]{_scope_text(rec.get('download_scope') or mapped, rec.get('scope_param') or param)}[/green]"
                  f" [dim]（下次检查生效）[/dim]")


@subscribe.command("check")
@click.argument("creator")
@click.option("--dry-run", is_flag=True,
              help="只发现不入队（排查用；不标记已见，下次还会算作新作品）")
@click.option("--max-new", type=int, default=3, show_default=True,
              help="本次最多入队几个，0 = 不限")
@click.option("--yes", "-y", is_flag=True, help="跳过确认（范围 all 时用）")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（管道/脚本友好）")
def subscribe_check(creator: str, dry_run: bool, max_new: int,
                    yes: bool, as_json: bool):
    """检查单个创作者有没有新作品（真抓主页，串行慢，别连着敲）。

    首次检查只建立基线：现有作品全部标记已见但一个都不下——订阅一个
    500 视频的博主不该把 500 个全下下来。
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    creators = _fetch_creators()
    if creators is None:
        return
    uid = _resolve_creator(creator, creators)
    if not uid:
        return

    rec = next((c for c in creators if c.get("sec_uid") == uid), {}) or {}
    if (rec.get("download_scope") or "") == "all" \
            and not _confirm_all("这个创作者", yes):
        return

    if not as_json:
        console.print("[dim]正在抓主页（串行、可能要几十秒）…[/dim]")

    code, data = _queue_api(
        "POST", f"/api/subscriptions/{uid}/check",
        {"download": not dry_run, "max_new": max_new},
        timeout=_API_TIMEOUT_LONG)
    if code != 200:
        if as_json:
            click.echo(json.dumps(
                {"error": f"HTTP {code}: {_detail_of(data)}" if code else str(data)},
                ensure_ascii=False))
        else:
            _fail_browser(code, data)
        return

    if not isinstance(data, dict):
        _queue_fail(code, data)
        return
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    name = ((data.get("nickname") or "").strip() or f"…{uid[-8:]}")
    console.print(f"[bold green]✓[/bold green] {escape(name)}：{data.get('message') or '-'}")

    extra = []
    if data.get("fetched"):
        extra.append(f"抓到 {data['fetched']} 个作品")
    if data.get("drift_blocked"):
        extra.append(f"水位线拦下 {data['drift_blocked']} 个老作品")
    if data.get("pending"):
        extra.append(f"还剩 {data['pending']} 个留到下次")
    if data.get("backfill_left"):
        extra.append(f"历史作品还剩 {data['backfill_left']} 待补")
    if extra:
        console.print(f"[dim]{' · '.join(extra)}[/dim]")
    if data.get("queued"):
        console.print("[dim]→ downloadkit queue list 看下载进度[/dim]")


@subscribe.command("check-all")
@click.option("--dry-run", is_flag=True,
              help="只发现不入队（排查用）")
@click.option("--max-new", type=int, default=3, show_default=True,
              help="单轮最多入队几个，0 = 不限")
@click.option("--scope", default=None, metavar="SCOPE",
              help="本轮临时覆盖下载范围（不落库）：only_new/backfill_n/all，"
                   "也接受 new/backfill")
@click.option("--scope-param", "scope_param", type=int, default=None,
              help="配合 --scope backfill_n 的 N")
@click.option("--yes", "-y", is_flag=True, help="跳过确认（--scope all 时用）")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（管道/脚本友好）")
def subscribe_check_all(dry_run: bool, max_new: int, scope: str | None,
                        scope_param: int | None, yes: bool, as_json: bool):
    """检查所有启用的订阅（串行抓主页，全部跑完才返回）。

    ⚠ 比单个 check 慢得多，每个创作者都要开一次主页。抖音限流很严，
      频繁跑会触发验证码中间页 —— 服务端撞到风控会自动中断整轮，
      后面没轮到的创作者留到下一轮。
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    mapped = None
    if scope is not None:
        mapped = _map_scope(scope)
        if not mapped:
            console.print(f"[red]下载范围只能是 only_new / backfill_n / all，收到 {scope!r}[/red]")
            return
        if mapped == "backfill_n":
            if scope_param is None:
                console.print("[red]--scope backfill_n 要配 --scope-param N[/red]")
                return
            if not (1 <= scope_param <= 9999):
                console.print("[red]往回补的个数要在 1-9999 之间[/red]")
                return
        elif scope_param is not None:
            console.print(f"[red]{mapped} 不带个数，只有 backfill_n 才要 --scope-param[/red]")
            return
        if mapped == "all" and not _confirm_all("本轮", yes):
            return

    if not as_json:
        console.print("[dim]正在逐个检查启用中的订阅（串行抓主页，可能要几分钟）…[/dim]")

    code, data = _queue_api(
        "POST", "/api/subscriptions/check-all",
        {"download": not dry_run, "max_new": max_new,
         "scope": mapped, "scope_param": str(scope_param or "")},
        timeout=_API_TIMEOUT_LONG)
    if code != 200:
        if as_json:
            click.echo(json.dumps(
                {"error": f"HTTP {code}: {_detail_of(data)}" if code else str(data)},
                ensure_ascii=False))
        else:
            _fail_browser(code, data)
        return

    if not isinstance(data, dict):
        _queue_fail(code, data)
        return
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    # run_round 拿到锁后才发现的「跳过」和 check_all 内部的意外异常，
    # 服务端都回 200 —— 得在这里分开说，别当成一轮跑完了报成功
    if data.get("skipped"):
        console.print(f"[yellow]本轮跳过："
                      f"{data.get('message') or data.get('reason') or '（无说明）'}[/yellow]")
        return
    if data.get("error"):
        console.print(f"[red]{escape(str(data['error']))}[/red]")
        return

    results = list(data.get("results") or [])
    if not results:
        console.print("[yellow]没有启用中的订阅[/yellow]（subscribe list 看看，或先 add）")
        return

    table = Table(title=f"检查结果（{len(results)} 个）", header_style="bold magenta")
    table.add_column("昵称", max_width=16, no_wrap=True)
    table.add_column("新作品", justify="right")
    table.add_column("入队", justify="right")
    table.add_column("结果", max_width=30)
    for r in results:
        name = ((r.get("nickname") or "").strip()
                or f"…{str(r.get('sec_uid') or '')[-8:]}")
        err = r.get("error")
        if err:
            row = (escape(name), "-", "-", f"[red]{escape(str(err))}[/red]")
        else:
            msg = r.get("message") or (
                "已建立基线，存量不下载" if r.get("baselined") else "-")
            row = (escape(name), str(r.get("new_count", 0)),
                   str(r.get("queued", 0)), escape(str(msg)))
        table.add_row(*row)
    console.print(table)

    console.print(
        f"合计: 创作者 {data.get('total', 0)} · 新发现 {data.get('new_found', 0)}"
        f" · 入队 {data.get('queued', 0)} · 失败 {data.get('errors', 0)}")
    if data.get("queued"):
        console.print("[dim]→ downloadkit queue list 看下载进度[/dim]")

    # 中断标记要显式喊出来：rate_limited / needs_login 时「合计」行看着像
    # 正常跑完，其实后面几个创作者根本没被检查到
    if data.get("stopped_at"):
        console.print(f"[dim]本轮中断于 {escape(str(data['stopped_at']))}，其后未检查[/dim]")
    if data.get("rate_limited"):
        console.print("[red]撞了风控 —— 等退避过去再跑，别连着敲[/red]")
    if data.get("needs_login"):
        console.print("[red]登录态失效 → 启动程序 → 设置 → 登录抖音，再重试[/red]")


def _poller_options(fn):
    """on / off / set 共用的轮询配置选项（按名字取值，顺序无关）。"""
    for opt in (
        click.option("--mode", type=click.Choice(["interval", "daily_at"]),
                     default=None,
                     help="调度模式：interval=按间隔 / daily_at=每天定点"),
        click.option("--daily-at", "daily_at", default=None, metavar="HH:MM",
                     help="每天几点检查（daily_at 模式），如 09:00"),
        click.option("--interval", "interval", type=int, default=None,
                     help="每 N 分钟一轮（越界会被服务端裁到合法区间）"),
        click.option("--max-new", "max_new", type=int, default=None,
                     help="单轮最多入队几个，0 = 不限"),
        click.option("--jitter", "jitter", type=int, default=None,
                     help="间隔抖动百分比（避免固定节奏撞风控），越界自动裁剪"),
    ):
        fn = opt(fn)
    return fn


def _poller_updates(mode: str | None, daily_at: str | None, interval: int | None,
                    max_new: int | None, jitter: int | None) -> dict:
    """把命令行选项翻成「只改这些字段」的请求体。

    只给 --daily-at 就推断 daily_at 模式、只给 --interval 就推断 interval
    模式 —— 用户敲「每天 9 点」的时候不想再被要求补一个 --mode。两个都给
    才要求显式 --mode，因为此时猜哪个都可能猜错。
    """
    if mode is None and daily_at is not None and interval is not None:
        raise click.UsageError(
            "--daily-at 和 --interval 同时给了，请补一个 --mode 指定用哪种")

    updates: dict = {}
    if daily_at is not None:
        updates["daily_at"] = daily_at
    if interval is not None:
        updates["interval_minutes"] = interval
    if max_new is not None:
        updates["max_new_per_check"] = max_new
    if jitter is not None:
        updates["jitter_percent"] = jitter

    if mode is not None:
        updates["mode"] = mode
    elif daily_at is not None:
        updates["mode"] = "daily_at"
    elif interval is not None:
        updates["mode"] = "interval"
    return updates


def _poller_show():
    """把 /api/subscriptions/poller 的状态摊成几行人话。"""
    code, data = _queue_api("GET", "/api/subscriptions/poller")
    if code != 200:
        _queue_fail(code, data)
        return
    if not isinstance(data, dict):
        _queue_fail(code, data)
        return

    on = bool(data.get("enabled"))
    lines = ["开关: " + ("[green]开启[/green]" if on else "[dim]关闭[/dim]")]

    if data.get("mode") == "daily_at":
        lines.append(f"模式: 每天 [bold]{data.get('daily_at') or '-'}[/bold] 检查")
    else:
        lines.append(f"模式: 每 [bold]{data.get('interval_minutes') or '-'}[/bold] 分钟一轮"
                     f"（抖动 {data.get('jitter_percent', 0)}%）")

    lines.append(f"单轮最多入队 {data.get('max_new_per_check', 0)} 个"
                 f" · 启用中的订阅 {data.get('creators_enabled', 0)} 个")

    nxt = data.get("next_run_at") or ""
    if nxt:
        lines.append(f"下次检查: {nxt}（{_ago(nxt)}）")
    elif on:
        lines.append("下次检查: 排期中（调度线程稍后会写进来）")
    else:
        lines.append("下次检查: 未排期（轮询已关闭）")

    if data.get("running"):
        lines.append("[yellow]有一轮检查正在跑[/yellow]")

    bo = data.get("backoff_until") or ""
    if bo:
        # 退避要看的是「还剩多久」，不是「多久以前」——退避截止时间一定在未来，
        # 拿 _ago（相对现在已过去多久）去算会得出「3 小时前」这种废话
        try:
            left_s = (datetime.strptime(str(bo)[:19], "%Y-%m-%d %H:%M:%S")
                      - datetime.now()).total_seconds()
        except ValueError:
            left_s = -1
        if left_s > 0:
            lines.append(f"[red]风控退避中，至 {bo}"
                         f"（还剩约 {max(1, int(left_s // 60))} 分钟）[/red]")
        else:
            lines.append(f"[dim]上一次退避已过期（原定 {bo}），可正常检查[/dim]")
    if data.get("needs_login"):
        lines.append("[red]登录态失效，需要重新扫码[/red]")

    rounds = data.get("rounds") or 0
    if rounds:
        last = data.get("last_result") or {}
        tail = (f"新 {last.get('new_found', 0)} · 入队 {last.get('queued', 0)}"
                f" · 失败 {last.get('errors', 0)}") if last else "无"
        lines.append(f"已跑 {rounds} 轮 · 上轮 {data.get('last_run_at') or '-'}: {tail}")
        if last.get("rate_limited"):
            lines.append("[red]上轮撞了风控[/red]")
        if last.get("needs_login"):
            lines.append("[red]上轮因未登录中断[/red]")
    else:
        lines.append("[dim]还没跑过任何一轮[/dim]")

    console.print("\n".join(lines))


def _poller_apply(body: dict, ok_msg: str) -> dict | None:
    code, data = _queue_api("POST", "/api/subscriptions/poller", body)
    if code != 200:
        _queue_fail(code, data)
        return None
    console.print(f"[bold green]✓[/bold green] {ok_msg}")
    return data if isinstance(data, dict) else {}


@subscribe.group("poller", invoke_without_command=True)
@click.pass_context
def subscribe_poller(ctx):
    """查看/启停自动轮询（后台按周期检查全部启用的订阅）。

    \b
    不带子命令 = 查看状态；子命令：
      on    开启（可顺手带 --interval / --daily-at 等改配置）
      off   关闭
      set   只改配置，不动开关
    """
    if ctx.invoked_subcommand is None:
        _poller_show()


@subscribe_poller.command("on")
@_poller_options
def poller_on(mode, daily_at, interval, max_new, jitter):
    """开启自动轮询（会清掉上次会话残留的风控退避）。"""
    body = _poller_updates(mode, daily_at, interval, max_new, jitter)
    body["enabled"] = True
    data = _poller_apply(body, "自动轮询已开启")
    if data:
        _poller_show()


@subscribe_poller.command("off")
def poller_off():
    """关闭自动轮询（不再自动检查，手动 check / check-all 不受影响）。"""
    data = _poller_apply({"enabled": False}, "自动轮询已关闭")
    if data:
        _poller_show()


@subscribe_poller.command("set")
@_poller_options
def poller_set(mode, daily_at, interval, max_new, jitter):
    """只改轮询配置，不动开关。"""
    body = _poller_updates(mode, daily_at, interval, max_new, jitter)
    if not body:
        raise click.UsageError(
            "没给要改的项。可选 --mode / --daily-at / --interval / --max-new / --jitter")
    data = _poller_apply(body, "轮询配置已更新")
    if data:
        _poller_show()


# ==================================================================
# 文件管理（P5-4）
# ==================================================================
# 一样走 HTTP：下载根目录是服务端按配置算出来的（get_download_dir()，
# 可能指向 NAS、也可能带自定义分类子目录），CLI 在本地猜一个路径很容易
# 对不上；删除与打开还必须过服务端的 safe_delete_path —— `..` 遍历和越出
# 下载目录由它统一挡成 403，CLI 不再自己实现一遍安全逻辑（两套校验各挡
# 各的反而更容易漏）。

_FILES_CAT = {"music": "音乐", "videos": "视频", "images": "图片",
              "animated": "动图", "others": "其他"}


def _fmt_size(n) -> str:
    """字节 → 人类可读（B / KB / MB / GB / TB）。"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    if n < 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _file_time(ts) -> str:
    """服务端给的 mtime 时间戳 → 年-月-日 时:分（解析不出给 '-'）。"""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "-"


def _confirm_or_skip(prompt: str, yes: bool) -> bool:
    """危险操作前确认；--yes 直接放行。返回 False 表示用户当场取消。

    和订阅那边的 _confirm_all 分开：那个把「全部历史作品」的后果文案
    写死在提示里了，删文件要的是另一套话。
    """
    if yes:
        return True
    try:
        click.confirm(prompt, abort=True)
    except click.Abort:
        console.print("[yellow]已取消[/yellow]")
        return False
    return True


@main.group()
def files():
    """下载文件管理（列出 / 删除 / 打开，走运行中服务的 /api/files/*）。

    \b
    Examples:
      downloadkit files ls
      downloadkit files ls videos
      downloadkit files rm music/a.mp3 music/b.mp3
      downloadkit files open videos/clip.mp4
      downloadkit files open videos/clip.mp4 --dir
    """
    pass


@files.command("ls")
@click.argument("category", default="all",
                type=click.Choice(["all", *_FILES_CAT]))
@click.option("--json", "as_json", is_flag=True, help="输出 JSON（管道/脚本友好）")
def files_ls(category: str, as_json: bool):
    """列出下载目录里的文件。

    CATEGORY 可选 music（音乐）/ videos（视频）/ images（图片）/
    animated（动图）/ others（其他，散在根目录的媒体文件），默认 all。
    输出按修改时间倒序——命令行下最想先看到的永远是「最近下的那个」。
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    code, data = _queue_api("GET", "/api/files")
    if code != 200:
        if as_json:
            # 管道侧也要结构化错误（含 HTTP 码），别只吐半截文本
            click.echo(json.dumps(
                {"error": f"HTTP {code}: {_detail_of(data)}" if code else str(data)},
                ensure_ascii=False))
        else:
            _queue_fail(code, data)
        return

    if not isinstance(data, dict):
        _queue_fail(code, data)
        return

    rows = list(data.get("files") or [])
    if category != "all":
        rows = [f for f in rows if f.get("category") == category]

    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        if category == "all":
            console.print("[yellow]下载目录里还没有文件[/yellow]")
            console.print("[dim]先跑一个下载，或按分类看：files ls videos[/dim]")
        else:
            console.print(f"[yellow]{_FILES_CAT[category]}分类下没有文件[/yellow]")
        return

    rows.sort(key=lambda f: f.get("time") or 0, reverse=True)

    table = Table(title=f"下载文件（{len(rows)} 个）",
                  header_style="bold magenta")
    table.add_column("分类", style="dim")
    # 文件名要原样可复制（用户得拿它去 files rm / open），所以 no_wrap
    # 不给 max_width——截断成「名…」就没法当参数用了
    table.add_column("文件名", no_wrap=True)
    table.add_column("大小", justify="right")
    table.add_column("修改时间", justify="right")

    total = 0
    counts: dict[str, int] = {}
    for f in rows:
        cat = str(f.get("category") or "")
        # 文件名是用户内容，可能自带方括号（rich 标记），必须 escape
        table.add_row(
            str(f.get("category_label") or _FILES_CAT.get(cat, cat)),
            escape(str(f.get("name") or "")),
            _fmt_size(f.get("size")),
            _file_time(f.get("time")),
        )
        counts[cat] = counts.get(cat, 0) + 1
        try:
            total += int(f.get("size") or 0)
        except (TypeError, ValueError):
            pass

    console.print(table)
    parts = [f"{label} {counts[c]}"
             for c, label in _FILES_CAT.items() if c in counts]
    console.print(f"共 {len(rows)} 个 · {_fmt_size(total)} · "
                  + " · ".join(parts))


files.add_command(files_ls, name="list")


@files.command("rm")
@click.argument("paths", nargs=-1, required=True)
@click.option("--yes", "-y", is_flag=True,
              help="跳过确认（删了不可恢复，批量跑才用它）")
def files_rm(paths: tuple, yes: bool):
    """删除一个或多个文件。

    PATH 用 files ls 列出的相对路径（如 music/a.mp3）——路径解析与安全
    校验都在服务端：`..` 遍历、越出下载目录一律 403 拒绝。
    """
    paths = [str(p).strip() for p in paths if str(p).strip()]
    if not paths:
        raise click.UsageError("没给要删的文件。先用 files ls 看路径。")

    # 危险操作：先把要删的东西摊开列清楚，别让用户对着一串参数猜
    console.print("[yellow]将删除以下文件（不可恢复）：[/yellow]")
    for p in paths:
        console.print(f"  · {escape(p)}")
    if not _confirm_or_skip(f"确认删除这 {len(paths)} 个文件", yes):
        return

    code, data = _queue_api("POST", "/api/files/batch-delete",
                            {"files": paths})
    if code != 200:
        _queue_fail(code, data)
        return
    if not isinstance(data, dict):
        _queue_fail(code, data)
        return

    deleted = list(data.get("deleted") or [])
    errors = list(data.get("errors") or [])

    for p in deleted:
        console.print(f"[bold green]✓[/bold green] 已删除 [green]{escape(str(p))}[/green]")
    # batch-delete 是「逐条记账」：单条失败不会让整个请求 403/500，
    # 所以失败必须逐条列出来，否则用户以为全删了
    for e in errors:
        if isinstance(e, dict):
            ep, er = str(e.get("path") or "?"), str(e.get("error") or "未知原因")
        else:
            ep, er = str(e), "未知原因"
        console.print(f"[red]✗ 删不掉 {escape(ep)}：{er}[/red]")

    if not deleted and not errors:
        console.print("[red]服务端没回任何删除结果（什么也没删）[/red]")
    else:
        tail = (f" · [red]失败 {len(errors)} 个[/red]" if errors else "")
        console.print(f"[dim]已删除 {len(deleted)} 个{tail}[/dim]")


@files.command("open")
@click.argument("path_")
@click.option("--dir", "as_dir", is_flag=True,
              help="打开文件所在目录，而不是文件本身")
def files_open(path_: str, as_dir: bool):
    """用系统默认程序打开下载目录内的文件（--dir 打开它所在的目录）。

    只给裸文件名也行（服务端会在下载目录里递归找同名文件，同名取第一个）。
    容器 / headless 环境下服务端弹不开程序，会回一条 NAS 上的路径，
    这里照原样转述。
    """
    endpoint = "/api/open-dir" if as_dir else "/api/open-file"
    code, data = _queue_api("POST", endpoint, {"path": path_})
    if code != 200:
        _queue_fail(code, data)
        return
    if not isinstance(data, dict):
        _queue_fail(code, data)
        return

    target = str(data.get("path") or path_)
    if data.get("status") == "headless":
        # 容器里没法真弹开，服务端给的是「它在哪」——照说，别假装打开了
        title = str(data.get("title") or "文件位置")
        console.print(f"[bold green]✓[/bold green] {title}: "
                      f"[green]{escape(target)}[/green]")
        nas = str(data.get("nas_path") or data.get("smb_path") or "")
        if nas:
            console.print(f"[dim]{escape(nas)}[/dim]")
    else:
        console.print(f"[bold green]✓[/bold green] 已打开 [green]{escape(target)}[/green]")


# ==================================================================
# 嗅探与书签（P5-5）
# ==================================================================
# 还是走 HTTP：L2 嗅探用的是服务进程里那个 DrissionPage 浏览器单例
# （_lock 串行、headless/有头按站点在进程内记忆），CLI 自己再起一份就是
# 两个浏览器抢同一批资源，还会丢掉「这个站回退过有头」的记忆。
#
# 退出码和 queue / subscribe 那两组不一样：那两组是「状态查询」，查到空
# 状态也算查成功（0）；这一组是「探测器」——sniff 没抓到流、书签导不进
# 链接，都意味着命令没做成它该做的事，给 1，脚本据此分支，不必解析中文。

# L2 预算服务端会裁到 10~60 秒，但浏览器启动 + WAF 挑战 + 播放器提升
# 都算在里面，客户端超时必须留足余量——服务端还在干活、客户端先报超时
# 就白跑了（和订阅抓主页同一个坑）。
_API_TIMEOUT_SNIFF = 120.0

_METHOD_LABEL = {"main": "主页面监听", "player": "播放器提升", "js": "JS Hook"}


def _probe_api(path: str, body, *, as_json: bool, timeout: float = 30.0,
               method: str = "POST") -> dict:
    """调服务端并统一处理失败：拿不到结果就以退出码 1 结束。

    --json 模式把错误也结构化到 stdout（管道侧不能只吐半截文本），
    普通模式走 _queue_fail 打中文。method 默认 POST——settings 那组
    有两个 GET 端点，传进来即可。
    """
    code, data = _queue_api(method, path, body, timeout=timeout)
    if code == 200 and isinstance(data, dict):
        return data
    msg = f"HTTP {code}: {_detail_of(data)}" if code else str(data)
    if as_json:
        click.echo(json.dumps({"error": msg}, ensure_ascii=False))
    else:
        _queue_fail(code, data)
    sys.exit(1)


def _die_local(msg: str, as_json: bool) -> None:
    """本地失败的收尾：文件读不了、0 条链接这类压根没走到服务端的情况。

    退出码同样是 1（和 _probe_api 一致），--json 侧照样吐 {"error": …}——
    不能因为没 HTTP 码就换一种收尾方式，管道侧只认得「1 = 没做成」。
    """
    if as_json:
        click.echo(json.dumps({"error": msg}, ensure_ascii=False))
    else:
        console.print(f"[red]{escape(msg)}[/red]")
    sys.exit(1)


@main.command()
@click.argument("url")
@click.option("--timeout", "-t", type=float, default=30.0,
              help="L2 总预算秒数（服务端会裁到 10~60）")
@click.option("--json", "as_json", is_flag=True,
              help="输出 JSON（服务端原样返回，管道/脚本友好）")
def sniff(url: str, timeout: float, as_json: bool):
    """L2 浏览器深度嗅探：真实浏览器打开页面抓 m3u8 / mp4 流地址。

    L0 直链、L1 静态解析都拿不到流时的最深层——过 WAF 挑战、监听网络、
    跨域 iframe 播放器提升。每条流自带 referer/ua，可直接进下载接口。

    退出码：0 = 命中至少一条流；1 = 没拿到（含连不上服务）。

    \b
    Examples:
      downloadkit sniff "https://example.com/watch/123"
      downloadkit sniff <url> --json | jq -r '.streams[].url'
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    data = _probe_api("/api/sniff", {"url": url, "timeout": timeout},
                      as_json=as_json, timeout=_API_TIMEOUT_SNIFF)

    streams = [s for s in (data.get("streams") or [])
               if isinstance(s, dict) and (s.get("url") or "")]

    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if streams else 1)

    if not streams:
        why = (str(data.get("error") or "")).strip() or "页面未发现流地址"
        console.print(f"[yellow]嗅探未命中：{escape(why)}[/yellow]")
        # 导航失败（死域名）和被 WAF 拦是两回事，别让用户对着同一个提示
        # 反复重试一个根本打不开的地址
        if data.get("nav_failed"):
            console.print("[dim]导航失败：这个地址本身打不开，换个源再试。[/dim]")
        sys.exit(1)

    method = _METHOD_LABEL.get(str(data.get("method") or ""),
                                str(data.get("method") or "-"))
    console.print(f"[bold green]✓[/bold green] 命中 {len(streams)} 条流 · "
                  f"{method} · {data.get('elapsed', 0)}s")
    title = (str(data.get("title") or "")).strip()
    if title:
        console.print(f"[dim]页面：{escape(title)}[/dim]")

    # 流地址走 click.echo 而不是 console.print：m3u8/mp4 地址动辄上百字符，
    # rich 按 80 列折行会把它从中间切断，用户就复制不全了。P5-2 的 Task ID
    # 是同一个坑（那次解法是 no_wrap），这里整行本身就比 80 宽，只能绕开。
    for i, s in enumerate(streams, 1):
        click.echo(f"[{i}] {s.get('kind') or '-'}  {s['url']}")

    referer = (str(data.get("referer") or "")).strip()
    if referer:
        click.echo(f"referer: {referer}")
    player_url = (str(data.get("player_url") or "")).strip()
    if player_url:
        click.echo(f"player: {player_url}")


@main.group()
def bookmarks():
    """浏览器书签导入（Netscape 格式 HTML，浏览器「导出书签」得到的那份）。

    \b
    Examples:
      downloadkit bookmarks import bookmarks.html
      downloadkit bookmarks import bookmarks.html --urls
      downloadkit bookmarks import bookmarks.html --json | jq '.links'
    """
    pass


def _read_bookmark_file(path: str) -> str:
    """按浏览器导出的惯例读书签 HTML（UTF-8，可带 BOM）。

    导出文件绝大多数是 UTF-8（浏览器 FileReader 也按 UTF-8 读）；万一在
    中文 Windows 上被别的工具转过码，再退回 cp936。但必须**真解不开**才
    退——把好好的 UTF-8 当 GBK 读会把标题读成乱码，还照样能解析成功，
    那种静默损坏最难查。
    """
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp936")
    except UnicodeDecodeError as e:
        # 抛 ValueError 而不是 click.ClickException：那个走 stderr，而这一组
        # 的失败信息都在 stdout（--json 侧要的是能直接 parse 的 {"error": …}）
        raise ValueError(
            f"书签文件编码认不出（既不是 UTF-8 也解不开 cp936）：{e}") from e


def _walk_bookmarks(nodes, depth: int = 0):
    """深度优先展平书签树，产出 (depth, kind, name, url)。

    用生成器而不是「先算完再截断」：书签动辄上千条，渲染到 limit 就该
    直接停下，不必先把整棵树走完。
    """
    for n in nodes or ():
        kind = str(n.get("type") or "")
        if kind == "folder":
            yield depth, "folder", str(n.get("name") or "未命名文件夹"), ""
            yield from _walk_bookmarks(n.get("children") or (), depth + 1)
        elif kind == "link":
            url = str(n.get("url") or "").strip()
            if url:
                yield depth, "link", str(n.get("title") or "").strip(), url


@bookmarks.command("import")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--urls", "as_urls", is_flag=True,
              help="一行一个 URL（去重保序，管道/脚本友好）")
@click.option("--limit", "-n", "limit", type=int, default=50,
              help="树视图最多显示多少条链接（0 = 不限）")
@click.option("--json", "as_json", is_flag=True,
              help="输出服务端原样返回（与 --urls 同给时以 --json 为准）")
def bookmarks_import(file: str, as_urls: bool, limit: int, as_json: bool):
    """导入书签 HTML 并批量解析出全部链接。

    服务端按 NETSCAPE-Bookmark 结构解析，返回树与统计（链接数 / 文件夹
    数）。默认渲染成缩进树，--urls 只吐链接，--json 吐原始结构。

    退出码：0 = 至少解析出一条链接；1 = 没解析到或读不了文件。
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    try:
        text = _read_bookmark_file(file)
    except OSError as e:
        _die_local(f"读不了 {file}：{e}", as_json)
    except ValueError as e:
        _die_local(str(e), as_json)

    data = _probe_api("/api/bookmarks/import", {"html": text}, as_json=as_json)

    tree = list(data.get("tree") or [])
    links = int(data.get("links") or 0)
    folders = int(data.get("folders") or 0)

    if links <= 0:
        # 服务端 0 链接时本来就会 400，走到这说明它认了文件却没吐出链接，
        # 同样是「没做成该做的事」
        _die_local("书签里没有可用链接", as_json)

    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if as_urls:
        # flatten_bookmarks 负责去重保序（首见标题为准），喂给下游工具前
        # 去重是必要的——浏览器书签里同一条链接存三份是常事
        for item in flatten_bookmarks(tree):
            click.echo(item["url"])
        return

    console.print(f"[bold green]✓[/bold green] 导入成功：{links} 条链接 / "
                  f"{folders} 个文件夹")
    shown = 0
    capped = False
    for depth, kind, name, url in _walk_bookmarks(tree):
        if limit and shown >= limit:
            capped = True
            break
        pad = "  " * depth
        if kind == "folder":
            console.print(f"{pad}[cyan]{escape(name)}/[/cyan]")
        else:
            shown += 1
            # 标题是网页内容，可能自带方括号（rich 标记），必须 escape
            console.print(f"{pad}• {escape(name or url)}")
    if capped and links > shown:
        console.print(f"[dim]… 还有 {links - shown} 条没显示"
                      f"（--limit 0 看全部，--urls 只要链接）[/dim]")


# ==================================================================
# 设置（P5-6）
# ==================================================================
# 走 HTTP 的理由：配置文件在**服务进程**的 HOME 下
# （~/.downloadkit/config.toml），CLI 自己写会写到另一份配置里去；而且
# 有些项保存后是服务进程当场改内存的（history_max_records 保存时就
# update_max_records），CLI 直接改文件只会弄出「文件改了、内存还是老值」
# 的分裂。

# 可写段就这三个：/api/settings/update 的请求模型（SettingsUpdateRequest）
# 只声明了 general/proxy/cookie，传别的段服务端当没看见 —— 只传
# subscription 时 config 为空，它照样回 {"status": "ok"}，那是假成功，
# 必须本地拦下，不能让人以为设进去了。
_UPDATABLE_SECTIONS = ("general", "proxy", "cookie")

# 数值范围抄产品自己的限制，不自创规则：
#   max_concurrent / history_max_records 是 index.html 里的 min/max；
#   max_concurrent < 1 更是要命 —— 下次启动 DownloadQueue(0) 会造出
#   asyncio.Semaphore(0)，所有下载一起卡死。
_SETTING_BOUNDS = {
    "general.max_concurrent": (1, 10),
    "general.history_max_records": (100, 100000),
}

# proxy 三态（与 downloadkit/proxy.MODES 同源，那儿导入进来更省事）
_PROXY_MODES = ("off", "system", "manual")


def _setting_schema() -> dict:
    """段名 → {键: 默认值}，当键表用，也当类型来源用。

    proxy.mode 是界面三态（off/system/manual）落盘的字段，DEFAULT_CONFIG
    里没有它（旧配置靠 resolve_mode 推导），但 settings.js 确实会存 ——
    少了这一条，`set proxy.mode manual` 会被当未知键拒掉，而那恰恰是
    最该能在命令行设的一个。
    """
    schema = {sec: dict(vals) for sec, vals in DEFAULT_CONFIG.items()}
    schema.setdefault("proxy", {})["mode"] = "system"
    return schema


def _resolve_setting_key(key: str, schema: dict,
                         extra: dict | None = None) -> tuple[str, str]:
    """把用户给的键解析成 (段名, 键名)。

    两层，和 P5-3 创作者解析一个套路：先按「段名.键名」精确匹配
    （settings get 打出来的就是这个形状，照抄即可），再按裸键名找唯一归属；
    多义（enabled 挂在 proxy / subscription 两段下）一律把候选列出来让人
    补全，绝不替他猜一个写进去 —— 猜错了写的是别的开关。

    extra 是配置里实际存在的键（settings get 会传）：配置文件里可能有键表
    没登记的历史遗留键，全量列出来却没有单键可查，等于把那一项藏了一半。
    set 不传 extra —— 它要在发出任何请求前就把参数判掉。
    """
    key = (key or "").strip()
    if "." in key:
        sec, _, name = key.partition(".")
        if sec in schema and name in schema[sec]:
            return sec, name
        node = (extra or {}).get(sec)
        if isinstance(node, dict) and name in node:
            return sec, name
        raise click.UsageError(
            f"没有这个设置项：{key}。运行 `downloadkit settings get` 看全部键。")
    # 裸键：命中的键名就是 key 本身，别去引用推导里不存在的变量
    hits = [(sec, key) for sec, names in schema.items() if key in names]
    for sec, node in (extra or {}).items():
        if isinstance(node, dict) and key in node and (sec, key) not in hits:
            hits.append((sec, key))
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise click.UsageError(
            f"没有这个设置项：{key}。运行 `downloadkit settings get` 看全部键。")
    secs = "、".join(sec for sec, _ in hits)
    raise click.UsageError(
        f"{key} 挂在多个段下（{secs}），写全成 段名.{key} 再来。")


def _coerce_setting(sec: str, name: str, raw: str, default) -> object:
    """按该键默认值的类型，把命令行上的一串字符转成配置值。

    类型必须守住：int 字段写成字符串，下次读它的人 int() 直接炸；bool
    字段更要命——`bool("false")` 是 True，写成字符串等于把开关悄悄反了。
    """
    key = f"{sec}.{name}"
    if isinstance(default, bool):
        v = (raw or "").strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off"):
            return False
        raise click.UsageError(
            f"{key} 是开关，只能给 true / false（也认 on/off、yes/no、1/0），"
            f"收到：{raw}")
    if isinstance(default, int):
        try:
            val = int(str(raw).strip())
        except (TypeError, ValueError):
            raise click.UsageError(
                f"{key} 是整数，收到：{raw}") from None
        bounds = _SETTING_BOUNDS.get(key)
        if bounds and not (bounds[0] <= val <= bounds[1]):
            raise click.UsageError(
                f"{key} 允许 {bounds[0]}~{bounds[1]}（与界面同一套限制），"
                f"收到：{val}")
        return val
    v = (raw or "").strip()
    if key == "proxy.mode":
        # resolve_mode 只认三态，写别的值会被静默忽略 —— 那就是「设成功了
        # 但根本没生效」，宁可当场报错
        if v not in _PROXY_MODES:
            raise click.UsageError(
                "proxy.mode 三态：off（关闭）/ system（跟随系统）/ "
                f"manual（手动），收到：{raw}")
        return v
    return raw


def _setting_value(cfg: dict, sec: str, name: str, schema: dict):
    """读一个键的当前值；proxy.mode 缺省时按服务端同一套推导回显。"""
    node = cfg.get(sec) or {}
    if name in node:
        return node[name]
    if f"{sec}.{name}" == "proxy.mode":
        from .proxy import resolve_mode
        return resolve_mode(node)
    return (schema.get(sec) or {}).get(name)


def _fmt_setting(v) -> str:
    """配置值 → 一行文本。bool 要吐 true/false，正好是 set 认得的写法。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


@main.group()
def settings():
    """查看与修改配置（读写运行中服务的 ~/.downloadkit/config.toml）。

    \b
    Examples:
      downloadkit settings get
      downloadkit settings get general.download_dir
      downloadkit settings set general.max_concurrent 5
      downloadkit settings proxy-test http://127.0.0.1:7890
    """
    pass


@settings.command("get")
@click.argument("key", required=False)
@click.option("--json", "as_json", is_flag=True,
              help="输出服务端原样返回（含 proxy_system；与键同给时以 --json 为准）")
def settings_get(key, as_json):
    """看当前配置；不给键就全部列出，给键只回值（管道友好）。

    \b
    Examples:
      downloadkit settings get
      downloadkit settings get general.download_dir
      downloadkit settings get proxy.mode
      downloadkit settings get --json | jq -r '.settings.general'
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    data = _probe_api("/api/settings/get", None, method="GET",
                      as_json=as_json)
    cfg = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    schema = _setting_schema()

    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if key:
        sec, name = _resolve_setting_key(key, schema, cfg)
        # 走 click.echo 而不是 console.print：路径可能上百字符，
        # rich 按 80 列折断了就不是原值了（和 sniff 的流地址同一个坑）
        click.echo(_fmt_setting(_setting_value(cfg, sec, name, schema)))
        return

    rows = []
    for sec, names in schema.items():
        for name in names:
            rows.append(f"{sec}.{name}")
    # 配置里有、键表里没有的历史遗留键也得看见，不然等于藏起来了
    for sec, node in cfg.items():
        if not isinstance(node, dict):
            continue
        for name in node:
            full = f"{sec}.{name}"
            if full not in rows:
                rows.append(full)
    width = max((len(r) for r in rows), default=0)
    derived_mode = "mode" not in (cfg.get("proxy") or {})
    for full in rows:
        sec, _, name = full.partition(".")
        value = _fmt_setting(_setting_value(cfg, sec, name, schema))
        note = ""
        if full == "proxy.mode" and derived_mode:
            note = "  # 未显式设置，按 enabled/地址推导"
        click.echo(f"{full:<{width}} = {value}{note}")

    sys_proxy = str(data.get("proxy_system") or "").strip()
    console.print(f"[dim]系统代理探测："
                  f"{escape(sys_proxy) if sys_proxy else '未检测到'}[/dim]")


@settings.command("set")
@click.argument("key")
@click.argument("value")
def settings_set(key, value):
    """改一个设置项（键写成 段名.键名，值按该键的类型解析）。

    只动这一个键，同段其它键原样保留（服务端按段合并、按键覆盖）。下载
    目录类的键会先过服务端校验，校验不过就不写——目录不存在会被顺带建
    出来，这点和界面一致。

    \b
    Examples:
      downloadkit settings set general.max_concurrent 5
      downloadkit settings set proxy.mode manual
      downloadkit settings set proxy.global http://127.0.0.1:7890
      downloadkit settings set cookie.douyin_path ""      # 置空
    """
    schema = _setting_schema()
    sec, name = _resolve_setting_key(key, schema)

    if sec not in _UPDATABLE_SECTIONS:
        hint = ("轮询那几项走 `downloadkit subscribe poller on|off|set`。"
                if sec == "subscription" else "")
        raise click.UsageError(
            f"{sec} 段不走 settings set（服务端 /api/settings/update 只收 "
            f"{'、'.join(_UPDATABLE_SECTIONS)}），设了也不会保存。{hint}")

    coerced = _coerce_setting(sec, name, value, schema[sec][name])

    # 下载目录先问服务端：路径存在但不是目录、或根本建不出来，现在就报，
    # 别等用户点下载才发现。校验会顺带把目录建出来（validate_download_dir
    # 就是这么干的，界面走的也是同一个端点）
    if name.startswith("download_dir"):
        info = _probe_api(
            f"/api/settings/download-dir-info?{urlencode({'path': coerced})}",
            None, method="GET", as_json=False)
        if not info.get("ok"):
            _die_local(f"目录不可用，没有保存：{info.get('message') or '-'}",
                       as_json=False)

    data = _probe_api("/api/settings/update", {sec: {name: coerced}},
                      as_json=False)
    after = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    stored = (after.get(sec) or {}).get(name)
    if stored == coerced:
        console.print(f"[bold green]✓[/bold green] {escape(f'{sec}.{name}')} = "
                      f"[green]{escape(_fmt_setting(stored))}[/green]")
    else:
        # 不假装成功：服务端存的和提交的对不上，原样报出来
        console.print(f"[yellow]已提交，但服务端存的是 "
                      f"{escape(_fmt_setting(stored))}（提交值 "
                      f"{escape(_fmt_setting(coerced))}）[/yellow]")


@settings.command("proxy-test")
@click.argument("proxy", required=False, default="")
@click.option("--url", default="",
              help="测试目标；留空用服务端内置目标（公网）。离线自测传 "
                   "http://127.0.0.1:PORT/")
@click.option("--json", "as_json", is_flag=True,
              help="输出服务端原样返回")
def settings_proxy_test(proxy, url, as_json):
    """测代理（或直连）通不通、延迟多少。不给代理地址就是测直连。

    服务端**永远回 200**——「代理不通」是测试结果不是服务故障，通不通放在
    body 的 ok 里。所以退出码由这里的 ok 定：0 = 通，1 = 不通（含连不上
    服务），和 sniff 那组的探测器语义一致。

    \b
    Examples:
      downloadkit settings proxy-test                          # 测直连
      downloadkit settings proxy-test http://127.0.0.1:7890
      downloadkit settings proxy-test http://127.0.0.1:7890 \
        --url http://127.0.0.1:1/                              # 离线造失败
    """
    if as_json:
        _quiet_logs(logging.ERROR)

    data = _probe_api("/api/proxy/test",
                      {"proxy": (proxy or "").strip(),
                       "url": (url or "").strip()},
                      as_json=as_json)
    ok = bool(data.get("ok"))
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if ok else 1)

    msg = str(data.get("message") or "-")
    if ok:
        console.print(f"[bold green]✓[/bold green] {escape(msg)}")
    else:
        console.print(f"[bold red]✗[/bold red] {escape(msg)}")
    sys.exit(0 if ok else 1)


# ==================================================================
# 收藏歌单（P5-7）
# ==================================================================
# 同样走 HTTP：歌单缓存在**服务端**的 ~/.downloadkit/collections.db 里，
# 而且 add / refresh 都会真的去解析歌单（网络 + 各平台适配器），CLI 自己
# 再实现一遍就是两套解析逻辑，两边对不上时谁也说不清哪个是真的。


def _coll_id(raw) -> int:
    """歌单 ID 必须是整数。

    它直接拼进 /api/collections/{id}，非数字会打到 FastAPI 匹配不上的
    路径上，回的是 404 Not Found —— 用户会以为「歌单不存在」，其实是自己
    ID 敲错了，这两种情况得分开说。
    """
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise click.UsageError(f"歌单 ID 必须是整数，收到：{raw}") from None


def _coll_api(method: str, path: str, body=None, *, as_json: bool):
    """这一组专用的请求层：失败打中文（或吐 JSON）后返回 None，**不改退出码**。

    和 _probe_api 唯一的区别是失败后走不走 sys.exit：本组是状态查询与数据
    管理，「歌单不存在」「歌单解析失败」是业务结果而不是「没做成该做的事」，
    所以沿用 queue / subscribe / files 的约定——提示完 return，退出码仍是 0；
    只有用法错误（ID 不是整数、参数缺失）才是 2。和 sniff / bookmarks /
    proxy-test 那组探测器的「没抓到就 1」不混用。
    """
    code, data = _queue_api(method, path, body)
    if code != 200:
        if as_json:
            click.echo(json.dumps(
                {"error": f"HTTP {code}: {_detail_of(data)}" if code else str(data)},
                ensure_ascii=False))
        else:
            _queue_fail(code, data)
        return None
    return data


@main.group()
def collections():
    """收藏歌单管理（需要 DownloadKit 正在运行，歌单缓存在它那边）。

    \b
    Examples:
      downloadkit collections list
      downloadkit collections add https://music.163.com/#/playlist?id=xxx
      downloadkit collections show 1
      downloadkit collections rename 1 我的歌单
      downloadkit collections refresh 1
      downloadkit collections rm 1
    """
    pass


@collections.command("list")
@click.option("--json", "as_json", is_flag=True,
              help="服务端原样返回（含 url 等全部字段）")
def collections_list(as_json):
    """列出全部收藏歌单（不含缓存曲目，要曲目用 show）。"""
    if as_json:
        _quiet_logs(logging.ERROR)
    rows = _coll_api("GET", "/api/collections", as_json=as_json)
    if rows is None:
        return
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        console.print("[dim]还没有收藏歌单。"
                      "`downloadkit collections add <歌单链接>` 加一个。[/dim]")
        return

    # URL 不进表格：网易云歌单链接动辄 60+ 字符，塞进去会把名称列挤没，
    # 而真正要复制给别的命令的是 ID；完整字段 --json 里都有
    table = Table(title=f"收藏歌单 · 共 {len(rows)} 个")
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("名称", overflow="fold")
    table.add_column("平台", no_wrap=True)
    table.add_column("曲目", justify="right", no_wrap=True)
    table.add_column("最近刷新", no_wrap=True)
    for c in rows:
        table.add_row(
            str(c.get("id", "-")),
            escape(str(c.get("name") or "")),
            escape(str(c.get("platform") or "-")),
            str(c.get("song_count", 0)),
            escape(str(c.get("refreshed_at") or c.get("created_at") or "-")),
        )
    console.print(table)


@collections.command("show")
@click.argument("id_", metavar="ID")
@click.option("-n", "--limit", default=0,
              help="最多显示几首曲目（0 = 全部）")
@click.option("--json", "as_json", is_flag=True,
              help="服务端原样返回")
def collections_show(id_, limit, as_json):
    """看一个收藏歌单的详情（含缓存的曲目列表）。

    \b
    Examples:
      downloadkit collections show 1
      downloadkit collections show 1 -n 10
      downloadkit collections show 1 --json | jq '.tracks[].title'
    """
    if as_json:
        _quiet_logs(logging.ERROR)
    detail = _coll_api("GET", f"/api/collections/{_coll_id(id_)}",
                       as_json=as_json)
    if detail is None:
        return
    if as_json:
        click.echo(json.dumps(detail, ensure_ascii=False, indent=2))
        return

    tracks = detail.get("tracks") if isinstance(detail.get("tracks"), list) else []
    shown = tracks[:limit] if limit > 0 else tracks
    # 标题/歌手都可能很长，先算宽度再决定要不要收进省略号
    table = Table(title=(f"{escape(str(detail.get('name') or ''))} · "
                         f"{len(tracks)} 首"))
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("标题", overflow="fold")
    table.add_column("歌手", overflow="fold")
    table.add_column("专辑", overflow="fold")
    for i, t in enumerate(shown, 1):
        table.add_row(
            str(i),
            escape(str(t.get("title") or "")),
            escape(str(t.get("artist") or "")),
            escape(str(t.get("album") or "")),
        )
    console.print(table)
    if len(shown) < len(tracks):
        console.print(f"[dim]只显示前 {len(shown)} 首，共 {len(tracks)} 首"
                      f"（-n 0 看全部）[/dim]")

    # 状态信息放表格下方：它们是给用户看的说明，不是曲目数据
    console.print(f"[dim]ID {detail.get('id')} · 平台 "
                  f"{escape(str(detail.get('platform') or '-'))} · "
                  f"创建 {escape(str(detail.get('created_at') or '-'))} · "
                  f"最近刷新 {escape(str(detail.get('refreshed_at') or '-'))}"
                  f"[/dim]")
    # 歌单链接走 click.echo：m3u8 那次的教训，长地址过 rich 会被折断
    click.echo(str(detail.get("url") or ""))


@collections.command("add")
@click.argument("url")
@click.option("-n", "--name", default="",
              help="自定义名称（留空用歌单本身的名称）")
@click.option("--json", "as_json", is_flag=True,
              help="服务端原样返回")
def collections_add(url, name, as_json):
    """收藏一个歌单（会真的去解析链接，得等一会儿）。

    \b
    Examples:
      downloadkit collections add https://music.163.com/#/playlist?id=xxx
      downloadkit collections add https://y.qq.com/n/rye/playlist/detail/xxx \\
        -n 睡前循环
    """
    if as_json:
        _quiet_logs(logging.ERROR)
    url = (url or "").strip()
    if not url:
        raise click.UsageError("没给歌单链接。")
    data = _coll_api("POST", "/api/collections",
                     {"url": url, "name": (name or "").strip()},
                     as_json=as_json)
    if data is None:
        return
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    tracks = data.get("tracks") if isinstance(data.get("tracks"), list) else []
    console.print(f"[bold green]✓[/bold green] 已收藏 "
                  f"[green]{escape(str(data.get('name') or url))}[/green]"
                  f"（ID {data.get('id')}，{len(tracks)} 首）")


@collections.command("rename")
@click.argument("id_", metavar="ID")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True,
              help="服务端原样返回")
def collections_rename(id_, name, as_json):
    """给收藏歌单改名。

    \b
    Examples:
      downloadkit collections rename 1 睡前循环
    """
    if as_json:
        _quiet_logs(logging.ERROR)
    name = (name or "").strip()
    if not name:
        raise click.UsageError("新名称不能为空。")
    data = _coll_api("PUT", f"/api/collections/{_coll_id(id_)}",
                     {"name": name}, as_json=as_json)
    if data is None:
        return
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    console.print(f"[bold green]✓[/bold green] 已改名为 "
                  f"[green]{escape(str(data.get('name') or name))}[/green]")


@collections.command("rm")
@click.argument("ids", nargs=-1, required=True, metavar="ID...")
@click.option("--yes", is_flag=True, help="跳过确认")
def collections_rm(ids, yes):
    """删除收藏歌单（删之前摊开列出目标并确认，--yes 跳过）。

    缓存的曲目会跟着一起删掉（服务端级联），收藏的歌单本身不受影响。

    \b
    Examples:
      downloadkit collections rm 1
      downloadkit collections rm 1 2 3 --yes
    """
    wanted = [_coll_id(x) for x in ids]
    rows = _coll_api("GET", "/api/collections", as_json=False)
    if rows is None:
        return
    by_id = {int(c["id"]): c for c in rows
             if str(c.get("id", "")).isdigit()}
    found = [i for i in dict.fromkeys(wanted) if i in by_id]
    missing = [i for i in dict.fromkeys(wanted) if i not in by_id]

    # 不存在的先说清楚，别和「删成功了」混在一起
    for i in missing:
        console.print(f"[yellow]收藏歌单不存在：{i}[/yellow]")
    if not found:
        return

    # 摊开列出要删的东西再问——让人对着一个干巴巴的 ID 确认是逼他记错
    for i in found:
        c = by_id[i]
        console.print(f"  [red]{i}[/red]  {escape(str(c.get('name') or ''))}"
                      f"  [dim]{escape(str(c.get('url') or ''))}[/dim]")
    if not _confirm_or_skip(f"确认删除这 {len(found)} 个收藏歌单？", yes):
        return

    ok = 0
    for i in found:
        if _coll_api("DELETE", f"/api/collections/{i}", as_json=False) is not None:
            ok += 1
    failed = len(found) - ok
    console.print(f"[bold green]✓[/bold green] 已删除 {ok} 个"
                  + (f"[yellow]，失败 {failed} 个[/yellow]" if failed else ""))


@collections.command("refresh")
@click.argument("ids", nargs=-1, required=True, metavar="ID...")
@click.option("--json", "as_json", is_flag=True,
              help="服务端原样返回")
def collections_refresh(ids, as_json):
    """重新解析歌单并替换缓存的曲目（逐个进行，每个都要走一次网络）。

    刷新会用歌单最新的名字覆盖自动命名的歌单（手动改过名的不动）。

    \b
    Examples:
      downloadkit collections refresh 1
      downloadkit collections refresh 1 2 3
    """
    if as_json:
        _quiet_logs(logging.ERROR)
    for raw in ids:
        i = _coll_id(raw)
        data = _coll_api("POST", f"/api/collections/{i}/refresh",
                         as_json=as_json)
        if data is None:
            continue                      # 这一个失败了，接着刷下一个
        if as_json:
            click.echo(json.dumps(data, ensure_ascii=False, indent=2))
            continue
        coll = data.get("collection") if isinstance(data.get("collection"), dict) else {}
        console.print(f"[bold green]✓[/bold green] #{i} "
                      f"{escape(str(coll.get('name') or ''))}："
                      f"{escape(str(data.get('message') or '刷新成功'))}")




# ==================================================================
# 下载历史（P5-7b）
# ==================================================================
# 历史缓存在**服务端**的 ~/.downloadkit/history.db，CLI 不直连——进程隔离时读
# 的是另一份文件，不隔离时两个进程共享同一 SQLite 也可能锁库。统一走 HTTP。
# 退出码沿用 P5-2 那组「状态查询」的约定：查到空也算查成功 -> 0；只有用法错误是 2。


def _hist_api(method: str, path: str, body=None):
    """这一组专用的请求层：失败打中文并返回 None，不改退出码。"""
    code, data = _queue_api(method, path, body)
    if code != 200:
        _queue_fail(code, data)
    return data


@main.group()
def history():
    """下载历史（需 DownloadKit 正在运行，缓存在它的 SQLite 里）。

    \b
    Examples:
      downloadkit history list
      downloadkit history search 晴天
      downloadkit history rm 1
      downloadkit history clear --yes
      downloadkit history count
    """
    pass


@history.command("list")
@click.option("-n", "--limit", default=20, show_default=True,
              help="最多显示几条（默认 20）")
@click.option("-o", "--offset", default=0, show_default=True,
              help="从第几条开始（默认从头）")
@click.option("--json", "as_json", is_flag=True,
              help="服务端原样返回（含 url/file_path 等全部字段）")
def history_list(limit, offset, as_json):
    """列出下载历史（默认最近 20 条，分页查看用 -o）。"""
    if as_json:
        _quiet_logs(logging.ERROR)
    rows = _hist_api("GET", f"/api/history?limit={limit}&offset={offset}",
                     body=None)
    if rows is None:
        return
    if not isinstance(rows, list):
        if as_json:
            click.echo(json.dumps({"error": f"服务端返回非列表"}, ensure_ascii=False))
        else:
            console.print("[red]服务端返回格式异常[/red]")
        return
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        console.print("[dim]还没有下载记录。下载一首歌或视频后这里会有内容。[/dim]")
        return

    table = Table(title=f"下载历史 · 共 {len(rows)} 条")
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("时间", no_wrap=True)
    table.add_column("标题", overflow="fold")
    table.add_column("作者", no_wrap=True)
    table.add_column("大小", justify="right", no_wrap=True)
    for r in rows:
        ts = r.get("downloaded_at") or "-"
        size = _hist_size(r.get("file_size") or 0)
        table.add_row(
            str(r.get("id", "-")),
            escape(str(ts)),
            escape(str(r.get("title") or "")),
            escape(str(r.get("author") or "")),
            size,
        )
    console.print(table)
    # 文件路径走 click.echo：长路径过 rich 会被折断，用户可能需要复制路径
    for r in rows:
        fp = r.get("file_path")
        if fp and str(fp).strip():
            click.echo(f"  [{r.get('id')}] {fp}")


@history.command("search")
@click.argument("keyword")
@click.option("-n", "--limit", default=20, show_default=True,
              help="最多返回几条")
@click.option("--json", "as_json", is_flag=True,
              help="服务端原样返回")
def history_search(keyword, limit, as_json):
    """按标题或作者搜索下载历史。"""
    if as_json:
        _quiet_logs(logging.ERROR)
    kw = (keyword or "").strip()
    if not kw:
        raise click.UsageError("搜索关键词不能为空。")
    rows = _hist_api("POST", f"/api/history/search?keyword={urllib.parse.quote(kw)}",
                     body=None)
    if rows is None:
        return
    if not isinstance(rows, list):
        if as_json:
            click.echo(json.dumps({"error": "服务端返回非列表"}, ensure_ascii=False))
        else:
            console.print("[red]服务端返回格式异常[/red]")
        return
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        console.print(f"[dim]没有找到和「{escape(kw)}」相关的记录。[/dim]")
        return

    table = Table(title=f"搜索结果 · {escape(kw)} · 共 {len(rows)} 条")
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("时间", no_wrap=True)
    table.add_column("标题", overflow="fold")
    table.add_column("作者", no_wrap=True)
    table.add_column("大小", justify="right", no_wrap=True)
    for r in rows:
        ts = r.get("downloaded_at") or "-"
        size = _hist_size(r.get("file_size") or 0)
        table.add_row(
            str(r.get("id", "-")),
            escape(str(ts)),
            escape(str(r.get("title") or "")),
            escape(str(r.get("author") or "")),
            size,
        )
    console.print(table)
    for r in rows:
        fp = r.get("file_path")
        if fp and str(fp).strip():
            click.echo(f"  [{r.get('id')}] {fp}")


@history.command("rm")
@click.argument("ids", nargs=-1, required=True, metavar="ID...")
@click.option("--yes", is_flag=True, help="跳过确认")
def history_rm(ids, yes):
    """删除一条或多条下载历史（删之前摊开列出目标并确认，--yes 跳过）。"""
    wanted = []
    for raw in ids:
        try:
            wanted.append(int(str(raw).strip()))
        except (TypeError, ValueError):
            raise click.UsageError(f"ID 必须是整数，收到：{raw}") from None

    # 先 GET list 确认哪些 ID 真实存在——count 只知总数，不知道具体 ID
    all_records = _hist_api("GET", "/api/history?limit=10000&offset=0")
    if all_records is None:
        return
    if not isinstance(all_records, list):
        console.print("[red]服务端返回格式异常[/red]")
        return
    existing_ids = {r.get("id") for r in all_records if isinstance(r, dict)}
    known = [i for i in dict.fromkeys(wanted) if i in existing_ids]
    unknown = [i for i in dict.fromkeys(wanted) if i not in existing_ids]

    if unknown:
        for i in unknown:
            console.print(f"[yellow]记录不存在：{i}[/yellow]")

    if not known:
        return

    # 摊开列出要删的——让人对着一个干巴巴的 ID 确认是逼他记错
    # 由于服务端不返回单条详情，只能打印 ID
    console.print(f"要删除的记录 ID：{', '.join(str(i) for i in known)}")
    if not _confirm_or_skip(f"确认删除这 {len(known)} 条记录？", yes):
        return

    ok = 0
    for i in known:
        data = _hist_api("DELETE", f"/api/history/{i}")
        if data is not None:
            ok += 1
    failed = len(known) - ok
    console.print(f"[bold green]✓[/bold green] 已删除 {ok} 条"
                  + (f"[yellow]，失败 {failed} 条[/yellow]" if failed else ""))


@history.command("clear")
@click.option("--yes", is_flag=True, help="跳过确认")
def history_clear(yes):
    """清空全部下载历史（危险操作，要求二次确认）。"""
    count = _hist_api("GET", "/api/history/count")
    if count is None:
        return
    n = count.get("count", 0) if isinstance(count, dict) else 0
    console.print(f"当前历史共有 [bold]{n}[/bold] 条记录，删除后不可恢复。")
    if not _confirm_or_skip("确认清空全部下载历史？", yes):
        return
    data = _hist_api("POST", "/api/history/clear")
    if data is None:
        return
    console.print(f"[bold green]✓[/bold green] 已清空，共删除 {n} 条记录")


@history.command("count")
@click.option("--json", "as_json", is_flag=True, help="服务端原样返回")
def history_count(as_json):
    """显示当前下载历史总条数。"""
    if as_json:
        _quiet_logs(logging.ERROR)
    data = _hist_api("GET", "/api/history/count", body=None)
    if data is None:
        return
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False))
        return
    n = data.get("count", 0) if isinstance(data, dict) else 0
    console.print(f"下载历史共 [bold]{n}[/bold] 条")


def _hist_size(size_bytes: int) -> str:
    """文件大小 -> 人类可读字符串。"""
    if not size_bytes:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}PB"


def _fmt_duration(sec) -> str:
    """秒数 → h:mm:ss / m:ss（无法解析返回 '-'）。"""
    try:
        sec = int(float(sec))
    except (TypeError, ValueError):
        return "-"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _public_info(info: dict) -> dict:
    """剥掉 raw（装的是原始对象，不可 JSON 序列化）。"""
    from .video_service import public_info
    return public_info(info)


def _render_parse(info: dict):
    """显示 parse_url 的结果（非 --json 模式）。"""
    lines = [
        f"[bold]{info.get('title') or '(无标题)'}[/bold]",
        f"[dim]作者:[/dim] {info.get('author') or '-'}    "
        f"[dim]类型:[/dim] {info.get('content_type') or '-'}    "
        f"[dim]时长:[/dim] {_fmt_duration(info.get('duration'))}",
    ]
    if info.get("cover"):
        lines.append(f"[dim]封面:[/dim] {info['cover']}")
    if info.get("suggested_name"):
        lines.append(f"[dim]将保存为:[/dim] [green]{info['suggested_name']}[/green]")
    if info.get("video_url"):
        lines.append(f"[dim]视频地址:[/dim] {str(info['video_url'])[:110]}")
    if info.get("video_urls"):
        lines.append(f"[dim]实况视频:[/dim] {len(info['video_urls'])} 个")
    if info.get("images"):
        lines.append(f"[dim]图片:[/dim] {len(info['images'])} 张")
    if info.get("is_playlist"):
        lines.append(f"[yellow]播放列表:[/yellow] {info.get('entry_count') or '?'} 项"
                     f"（用 -e/--episodes 展开选集）")
    console.print(Panel.fit("\n".join(lines),
                            title=f"{info.get('platform')} 解析结果"))

    formats = info.get("formats")
    if formats:
        table = Table(title="可用格式", show_header=True,
                      header_style="bold magenta")
        table.add_column("quality", style="cyan")
        table.add_column("ext")
        table.add_column("高度", justify="right")
        table.add_column("大小", justify="right")
        for f in formats[:15]:
            size = f.get("filesize")
            human = f"{size / 1048576:.1f} MB" if size else "-"
            table.add_row(str(f.get("quality") or "-"),
                          str(f.get("ext") or "-"),
                          str(f.get("height") or "-"),
                          human)
        console.print(table)


def _render_episodes(r: dict):
    """显示 expand_episodes 的结果。"""
    if not r.get("count"):
        console.print(f"[red]未找到选集: {r.get('error') or '无结果'}[/red]")
        console.print("[dim]可尝试直接解析单集链接[/dim]")
        return
    console.print(Panel.fit(
        f"[bold cyan]{r.get('title') or '(无标题)'}[/bold cyan]\n"
        f"方式: {r.get('method')}  |  选集: {r.get('count')}  "
        f"|  耗时: {r.get('elapsed')}s",
        title="选集展开",
    ))
    for gi, g in enumerate(r.get("groups", []), 1):
        console.print(f"[bold]组 {gi}:[/bold] {g.get('template')} —— "
                      f"[green]{g.get('count')}[/green] 集")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=5)
        table.add_column("标题", style="cyan", width=42)
        table.add_column("URL", style="dim", width=50)
        for i, it in enumerate(g.get("items", []), 1):
            table.add_row(str(i), str(it.get("label") or "")[:40],
                          str(it.get("url") or "")[:48])
        console.print(table)


def _render_done(paths):
    """显示 download_parsed 的产物。"""
    if not paths:
        console.print("[yellow]没有产物[/yellow]")
        return
    total = sum(p.stat().st_size for p in paths)
    human = (f"{total / 1048576:.1f} MB" if total > 1048576
             else f"{total / 1024:.1f} KB")
    if len(paths) == 1:
        console.print(f"  [green]Saved[/green] {paths[0]} ({human})")
    else:
        console.print(f"  [green]Saved[/green] {len(paths)} files ({human})")
        for i, p in enumerate(paths, 1):
            s = p.stat().st_size
            sz = f"{s / 1024:.1f} KB" if s < 1048576 else f"{s / 1048576:.1f} MB"
            console.print(f"    {i}. {p.name[:60]} ({sz})")


def _pick_indexes(choice: str, n: int) -> list[int]:
    """'1,3' / '1-4' / 'a' → 0 基索引列表（越界/非法剔除，去重保序）。"""
    choice = (choice or "").strip()
    if not choice:
        return []
    if choice.lower() == "a":
        return list(range(n))
    picked: list[int] = []
    for part in (p.strip() for p in choice.split(",")):
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                for i in range(int(a), int(b) + 1):
                    if 1 <= i <= n:
                        picked.append(i - 1)
            except ValueError:
                pass
        elif part.isdigit():
            i = int(part)
            if 1 <= i <= n:
                picked.append(i - 1)
    return sorted(dict.fromkeys(picked))


def _parse_selection(choice: str, songs: list) -> list:
    selected = []
    if choice.strip().lower() == "a":
        return songs
    parts = [p.strip() for p in choice.split(",")]
    for part in parts:
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(songs):
                selected.append(songs[idx])
        elif "-" in part:
            try:
                start, end = part.split("-", 1)
                for idx in range(int(start) - 1, int(end)):
                    if 0 <= idx < len(songs):
                        selected.append(songs[idx])
            except ValueError:
                pass
    return selected


def _download_selected(selected: list):
    console.print(f"\n[bold]Downloading [cyan]{len(selected)}[/cyan] songs...[/bold]\n")
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        overall = progress.add_task("[cyan]Overall", total=len(selected))
        success, failed = 0, 0
        for song in selected:
            task = progress.add_task(f"[dim]{song.title[:30]}", total=100)
            result = run_async(download_song(song, progress=None))
            progress.update(task, completed=100, visible=False)
            progress.update(overall, advance=1)
            if result:
                success += 1
            else:
                failed += 1

    console.print(f"\n[bold green]Done![/bold green] Success [green]{success}[/green], Failed [red]{failed}[/red]")
    console.print(f"Files saved in: [dim]./downloads/[/dim]")


if __name__ == "__main__":
    main()


