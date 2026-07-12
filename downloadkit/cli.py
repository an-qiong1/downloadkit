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


def run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)


@click.group()
@click.version_option(version="0.3.0", prog_name="downloadkit")
def main():
    """downloadkit -- Multi-platform resource downloader.

    Supports music search/download (QQ Music, NetEase),
    video download (Douyin, Bilibili, YouTube, Xiaohongshu),
    and playlist import.
    """
    pass


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
@click.option("-o", "--output", default="./downloads", show_default=True, help="Output directory")
def douyin(input_text: str, output: str):
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
        console.print(f"\n[bold green]Done![/bold green] Saved {len(paths)} files to [green]{output}[/green] ({human})")
        for i, p in enumerate(paths, 1):
            size = p.stat().st_size
            s = f"{size / 1024:.1f} KB" if size < 1048576 else f"{size / 1048576:.1f} MB"
            console.print(f"  {i}. [green]{p.name}[/green] ({s})")


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


