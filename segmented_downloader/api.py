"""
Convenience High-Level API for one-line integration.
"""

from typing import Optional, Callable
from .downloader import SegmentedDownloader, DownloadConfig


def download(
    url: str,
    output_path: Optional[str] = None,
    connections: int = 8,
    max_speed_bps: float = 0.0,
    dynamic_split: bool = True,
    on_progress: Optional[Callable[[SegmentedDownloader], None]] = None,
    wait: bool = True
) -> SegmentedDownloader:
    """
    Downloads a file with multi-threaded segmented downloading and resume support.

    :param url: URL of the file to download
    :param output_path: Destination path on disk (inferred if None)
    :param connections: Number of concurrent parallel connections (default 8)
    :param max_speed_bps: Bandwidth limit in bytes/sec (0 for unlimited)
    :param dynamic_split: Enable IDM-style dynamic segment splitting
    :param on_progress: Optional callback invoked on progress updates
    :param wait: If True, blocks until download completes
    :return: SegmentedDownloader instance
    """
    config = DownloadConfig(
        connections=connections,
        max_speed_bps=max_speed_bps,
        dynamic_split=dynamic_split
    )
    downloader = SegmentedDownloader(
        url=url,
        output_path=output_path,
        config=config,
        on_progress=on_progress
    )
    downloader.start(wait=wait)
    return downloader
