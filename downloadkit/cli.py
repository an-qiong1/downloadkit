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

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
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
@click.version_option(version="0.4.1", prog_name="downloadkit")
@click.option("-v", "--verbose", is_flag=True,
              help="显示详细日志（默认已压掉 INFO，保持界面干净）")
def main(verbose: bool):
    """downloadkit -- Multi-platform resource downloader.

    \b
    Music:    search / playlist / download（QQ音乐、网易云、酷我、咪咕…）
    Video:    parse（只解析）/ video（解析+下载，支持抖音、B站、YouTube、
              小红书、以及任意网页/直链的 generic 兜底）
    Douyin:   douyin（支持分享文本）
    """
    _quiet_logs(logging.INFO if verbose else logging.WARNING)


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


