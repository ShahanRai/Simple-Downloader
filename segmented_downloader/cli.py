"""
Interactive CLI for Segmented Downloader with Rich Visual Progress.
Displays per-connection segment progress bars identical to IDM's transfer dialog.
"""

import sys
import argparse
import time
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.progress import Progress, BarColumn, TextColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from rich.panel import Panel
from rich.layout import Layout

from .downloader import SegmentedDownloader, DownloadConfig
from .model import DownloadStatus


def format_bytes(n: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:3.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def main():
    parser = argparse.ArgumentParser(
        description="IDM-Style Segmented Multi-Connection Downloader CLI"
    )
    parser.add_argument("url", help="URL of the file to download")
    parser.add_argument("-o", "--output", help="Target output file path", default=None)
    parser.add_argument("-c", "--connections", type=int, help="Number of parallel connections", default=8)
    parser.add_argument("-s", "--speed-limit", type=float, help="Bandwidth limit in KB/s (0 for unlimited)", default=0.0)
    parser.add_argument("--no-dynamic-split", action="store_true", help="Disable dynamic segment splitting")

    args = parser.parse_args()
    console = Console()

    config = DownloadConfig(
        connections=args.connections,
        max_speed_bps=args.speed_limit * 1024.0,
        dynamic_split=not args.no_dynamic_split
    )

    console.print(Panel.fit(
        f"[bold cyan]IDM-Style Segmented Downloader[/bold cyan]\n"
        f"Target URL: [green]{args.url}[/green]\n"
        f"Parallel Connections: [yellow]{args.connections}[/yellow] | Dynamic Segmentation: [magenta]{config.dynamic_split}[/magenta]",
        title="[bold blue]Initialization[/bold blue]"
    ))

    downloader = SegmentedDownloader(url=args.url, output_path=args.output, config=config)

    def generate_dashboard() -> Panel:
        meta = downloader.metadata
        if not meta:
            return Panel("Probing server capabilities...")

        table = Table(title=f"Parallel Connection Segments ({len(meta.segments)} active)", expand=True)
        table.add_column("Conn #", justify="center", style="cyan", width=8)
        table.add_column("Range (Bytes)", style="dim", width=26)
        table.add_column("Downloaded", justify="right", style="green", width=14)
        table.add_column("Remaining", justify="right", style="yellow", width=14)
        table.add_column("Progress", style="magenta", width=18)
        table.add_column("Status", justify="center", style="bold", width=12)

        for s in meta.segments:
            range_str = f"{s.start_byte:,} - {s.end_byte:,}"
            pct = s.progress_pct
            bar_len = 10
            filled = int(bar_len * (pct / 100.0))
            bar = "█" * filled + "░" * (bar_len - filled)
            status_style = "green" if s.status == "COMPLETED" else "yellow" if s.status == "DOWNLOADING" else "dim"

            table.add_row(
                f"#{s.id + 1}",
                range_str,
                format_bytes(s.downloaded_bytes),
                format_bytes(s.remaining_bytes),
                f"[{bar}] {pct:.1f}%",
                f"[{status_style}]{s.status}[/{status_style}]"
            )

        total_pct = meta.progress_pct
        speed_str = format_bytes(int(downloader.current_speed_bps)) + "/s"
        eta_str = f"{int(downloader.eta_seconds)}s" if downloader.eta_seconds > 0 else "--"

        summary = (
            f"\n[bold]Overall Progress:[/] {format_bytes(meta.total_downloaded)} / {format_bytes(meta.file_size)} "
            f"({total_pct:.1f}%) | [bold]Speed:[/] [green]{speed_str}[/] | [bold]ETA:[/] [yellow]{eta_str}[/]"
        )

        return Panel(
            table,
            title=f"[bold]Downloading: {meta.output_path}[/] ({summary})"
        )

    downloader.start(wait=False)

    if console.is_terminal:
        try:
            with Live(console=console, refresh_per_second=4) as live:
                while True:
                    live.update(generate_dashboard())
                    if downloader.metadata and downloader.metadata.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                        break
                    time.sleep(0.25)
        except Exception:
            pass
    else:
        # Non-terminal / piped output fallback
        while True:
            if downloader.metadata:
                meta = downloader.metadata
                pct = meta.progress_pct
                speed_str = format_bytes(int(downloader.current_speed_bps)) + "/s"
                print(f"Downloading: {pct:.1f}% ({format_bytes(meta.total_downloaded)} / {format_bytes(meta.file_size)}) at {speed_str}", flush=True)
                if meta.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                    break
            time.sleep(0.5)

    if downloader.metadata and downloader.metadata.status == DownloadStatus.COMPLETED:
        console.print(f"\n[bold green]Download complete:[/] {downloader.output_path}")
    elif downloader.error:
        console.print(f"\n[bold red]Download failed:[/] {downloader.error}")


if __name__ == "__main__":
    main()
