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
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.markup import escape
from rich import print as rprint

from .searcher import search_all
from .playlist import parse_playlist
from .downloader import download_song, download_batch
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


