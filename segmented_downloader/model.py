"""
Data models and state representations for segmented downloads.
Mirrors the CFilePart and CFragmentsList data structures identified in IDM.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional
import json
import os


class DownloadStatus(str, Enum):
    INITIALIZING = "INITIALIZING"
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SegmentStatus(str, Enum):
    PENDING = "PENDING"
    DOWNLOADING = "DOWNLOADING"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    FAILED = "FAILED"


@dataclass
class Segment:
    """
    Represents an individual byte range segment (equivalent to IDM's CFilePart).
    """
    id: int
    start_byte: int
    end_byte: int
    current_byte: int
    status: SegmentStatus = SegmentStatus.PENDING
    speed_bps: float = 0.0

    @property
    def total_bytes(self) -> int:
        return max(0, self.end_byte - self.start_byte + 1)

    @property
    def downloaded_bytes(self) -> int:
        return max(0, self.current_byte - self.start_byte)

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.end_byte - self.current_byte + 1)

    @property
    def progress_pct(self) -> float:
        if self.total_bytes <= 0:
            return 100.0
        return min(100.0, (self.downloaded_bytes / self.total_bytes) * 100.0)

    def to_dict(self):
        d = asdict(self)
        d['status'] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict):
        data_copy = data.copy()
        data_copy['status'] = SegmentStatus(data_copy['status'])
        return cls(**data_copy)


@dataclass
class DownloadMetadata:
    """
    Persistent state for a download job (allows exact pause and resume).
    """
    url: str
    output_path: str
    file_size: int
    accepts_ranges: bool
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    status: DownloadStatus = DownloadStatus.INITIALIZING
    segments: List[Segment] = field(default_factory=list)
    created_at: float = 0.0

    @property
    def state_path(self) -> str:
        return f"{self.output_path}.state.json"

    @property
    def total_downloaded(self) -> int:
        return sum(s.downloaded_bytes for s in self.segments)

    @property
    def progress_pct(self) -> float:
        if self.file_size <= 0:
            return 0.0
        return min(100.0, (self.total_downloaded / self.file_size) * 100.0)

    def save(self):
        """Atomically saves the download state to JSON journal."""
        state_file = self.state_path
        tmp_file = f"{state_file}.tmp"
        payload = {
            "url": self.url,
            "output_path": self.output_path,
            "file_size": self.file_size,
            "accepts_ranges": self.accepts_ranges,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "status": self.status.value,
            "created_at": self.created_at,
            "segments": [s.to_dict() for s in self.segments]
        }
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_file, state_file)

    @classmethod
    def load(cls, state_path: str) -> Optional["DownloadMetadata"]:
        """Loads state from disk if exists."""
        if not os.path.exists(state_path):
            return None
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            segments = [Segment.from_dict(s) for s in data.get("segments", [])]
            return cls(
                url=data["url"],
                output_path=data["output_path"],
                file_size=data["file_size"],
                accepts_ranges=data["accepts_ranges"],
                etag=data.get("etag"),
                last_modified=data.get("last_modified"),
                status=DownloadStatus(data.get("status", DownloadStatus.PAUSED.value)),
                segments=segments,
                created_at=data.get("created_at", 0.0)
            )
        except Exception:
            return None
