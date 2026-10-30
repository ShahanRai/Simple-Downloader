"""
Segmented Downloader - High-Performance Multi-Connection Download Engine
Inspired by Internet Download Manager (IDM) Dynamic Segmentation Architecture
"""

from .downloader import SegmentedDownloader, DownloadConfig
from .model import Segment, DownloadMetadata, DownloadStatus, SegmentStatus
from .api import download
from .queue_manager import QueueManager, DownloadTask
from .server import IDMAPIServer

__all__ = [
    "SegmentedDownloader",
    "DownloadConfig",
    "DownloadStatus",
    "SegmentStatus",
    "Segment",
    "DownloadMetadata",
    "download",
    "QueueManager",
    "DownloadTask",
    "IDMAPIServer"
]
