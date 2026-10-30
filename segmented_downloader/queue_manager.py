"""
Queue and Task Manager for IDM Segmented Downloader.
Coordinates multiple concurrent downloads, queue persistence, category classification,
and real-time metrics aggregation.
"""

import os
import json
import time
import uuid
import threading
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field, asdict

from .downloader import SegmentedDownloader, DownloadConfig
from .model import DownloadStatus, SegmentStatus
from .protocol import probe_url, DEFAULT_USER_AGENT
from .youtube import is_youtube_or_streaming_url, probe_youtube_video, YouTubeDownloaderWorker


def get_default_storage_dir() -> str:
    """Returns persistent application data directory for Internet Downloader."""
    app_data = os.getenv("APPDATA")
    if app_data:
        path = os.path.join(app_data, "InternetDownloader")
        try:
            os.makedirs(path, exist_ok=True)
            test_f = os.path.join(path, ".test_write")
            with open(test_f, "w") as f:
                f.write("ok")
            os.remove(test_f)
            return path
        except Exception:
            pass

    path = os.path.join(os.path.expanduser("~"), ".internet_downloader")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:
        local_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.makedirs(local_dir, exist_ok=True)
        return local_dir


def infer_category(filename: str) -> str:
    """Classifies file into IDM categories based on extension."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".dmg"]:
        return "Compressed"
    elif ext in [".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v"]:
        return "Video"
    elif ext in [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus"]:
        return "Music"
    elif ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".epub", ".mobi"]:
        return "Documents"
    elif ext in [".exe", ".msi", ".bat", ".cmd", ".apk", ".jar", ".appx"]:
        return "Programs"
    return "General"


@dataclass
class DownloadTask:
    id: str
    url: str
    output_path: str
    filename: str
    file_size: int = 0
    downloaded_bytes: int = 0
    status: str = DownloadStatus.INITIALIZING.value
    connections: int = 8
    max_speed_bps: float = 0.0
    speed_bps: float = 0.0
    eta_seconds: float = 0.0
    category: str = "General"
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error_message: Optional[str] = None

    @property
    def progress_pct(self) -> float:
        if self.file_size <= 0:
            return 0.0
        return min(100.0, (self.downloaded_bytes / self.file_size) * 100.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


class QueueManager:
    """
    Thread-safe Queue Manager for concurrent and scheduled download tasks.
    """
    _instance = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = QueueManager()
            return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            self.db_path = os.path.join(get_default_storage_dir(), "tasks_queue.json")
        else:
            self.db_path = db_path

        self._lock = threading.RLock()
        self.tasks: Dict[str, DownloadTask] = {}
        self.downloaders: Dict[str, SegmentedDownloader] = {}
        self.max_active_tasks: int = 4
        self.global_speed_limit_bps: float = 0.0
        self.default_download_dir: str = os.path.join(os.path.expanduser("~"), "Downloads")

        self.on_task_added: Optional[Callable[[DownloadTask], None]] = None
        self.on_task_updated: Optional[Callable[[DownloadTask], None]] = None
        self.on_task_removed: Optional[Callable[[str], None]] = None

        self._load_tasks()

    def _load_tasks(self):
        with self._lock:
            if os.path.exists(self.db_path):
                try:
                    with open(self.db_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for item in data:
                            task = DownloadTask.from_dict(item)
                            # Any task that was DOWNLOADING before shutdown becomes PAUSED
                            if task.status == DownloadStatus.DOWNLOADING.value:
                                task.status = DownloadStatus.PAUSED.value
                            self.tasks[task.id] = task
                except Exception as e:
                    print(f"Error loading tasks: {e}")

    def save_tasks(self):
        with self._lock:
            try:
                data = [task.to_dict() for task in self.tasks.values()]
                temp_path = f"{self.db_path}.tmp"
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                if os.path.exists(self.db_path):
                    os.replace(temp_path, self.db_path)
                else:
                    os.rename(temp_path, self.db_path)
            except Exception as e:
                print(f"Error saving tasks: {e}")

    def add_task(
        self,
        url: str,
        output_dir: Optional[str] = None,
        custom_filename: Optional[str] = None,
        connections: int = 16,
        speed_limit_kb: float = 0.0,
        auto_start: bool = True,
        user_agent: str = DEFAULT_USER_AGENT
    ) -> DownloadTask:
        """Adds a new download task to queue and optionally starts it."""
        dest_dir = output_dir or self.default_download_dir
        os.makedirs(dest_dir, exist_ok=True)

        task_id = str(uuid.uuid4())[:8]

        # Probe server for filename and size if not supplied
        if is_youtube_or_streaming_url(url):
            yt_info = probe_youtube_video(url)
            filename = custom_filename or yt_info.get("title", f"YouTube_{task_id}.mp4")
            file_size = yt_info.get("file_size", 0)
            category = "Video"
        elif not custom_filename:
            try:
                probe = probe_url(url, user_agent=user_agent)
                filename = probe.filename
                file_size = probe.file_size
                category = infer_category(filename)
            except Exception:
                filename = f"download_{task_id}.bin"
                file_size = 0
                category = "General"
        else:
            filename = custom_filename
            file_size = 0
            category = infer_category(filename)

        output_path = os.path.join(dest_dir, filename)

        task = DownloadTask(
            id=task_id,
            url=url,
            output_path=output_path,
            filename=filename,
            file_size=file_size,
            connections=connections,
            max_speed_bps=speed_limit_kb * 1024.0,
            category=category,
            status=DownloadStatus.PENDING.value
        )

        with self._lock:
            self.tasks[task_id] = task
            self.save_tasks()

        if self.on_task_added:
            self.on_task_added(task)

        if auto_start:
            self.start_task(task_id)

        return task

    def start_task(self, task_id: str):
        """Starts or resumes a download task."""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return

            if task.status == DownloadStatus.COMPLETED.value:
                return

            if is_youtube_or_streaming_url(task.url):
                worker = YouTubeDownloaderWorker(
                    url=task.url,
                    output_path=task.output_path,
                    on_progress=lambda pct, dl, tot, spd, eta: self._handle_yt_progress(task_id, pct, dl, tot, spd, eta),
                    on_complete=lambda path: self._handle_complete(task_id, path),
                    on_error=lambda err: self._handle_error(task_id, err)
                )
                self.downloaders[task_id] = worker
                task.status = DownloadStatus.DOWNLOADING.value
                self.save_tasks()
                if self.on_task_updated:
                    self.on_task_updated(task)
                worker.start()
                return

            config = DownloadConfig(
                connections=task.connections,
                max_speed_bps=task.max_speed_bps,
                dynamic_split=True
            )

            downloader = SegmentedDownloader(
                url=task.url,
                output_path=task.output_path,
                config=config,
                on_progress=lambda d: self._handle_progress(task_id, d),
                on_complete=lambda path: self._handle_complete(task_id, path),
                on_error=lambda err: self._handle_error(task_id, err)
            )

            self.downloaders[task_id] = downloader
            task.status = DownloadStatus.DOWNLOADING.value
            self.save_tasks()

        if self.on_task_updated:
            self.on_task_updated(task)

        # Start non-blocking
        threading.Thread(target=lambda: downloader.start(wait=False), daemon=True).start()

    def _handle_progress(self, task_id: str, downloader: SegmentedDownloader):
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or not downloader.metadata:
                return

            task.file_size = downloader.metadata.file_size
            task.downloaded_bytes = downloader.metadata.total_downloaded
            task.speed_bps = downloader.current_speed_bps
            task.eta_seconds = downloader.eta_seconds
            task.status = downloader.metadata.status.value

        if self.on_task_updated:
            self.on_task_updated(task)

    def _handle_yt_progress(self, task_id: str, pct: float, downloaded: int, total: int, speed: float, eta: float):
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            if total > 0:
                task.file_size = total
            task.downloaded_bytes = downloaded
            task.speed_bps = speed
            task.eta_seconds = eta
            task.status = DownloadStatus.DOWNLOADING.value

        if self.on_task_updated:
            self.on_task_updated(task)

    def _handle_complete(self, task_id: str, output_path: str):
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task.status = DownloadStatus.COMPLETED.value
            task.downloaded_bytes = task.file_size if task.file_size > 0 else task.downloaded_bytes
            task.speed_bps = 0.0
            task.eta_seconds = 0.0
            task.completed_at = time.time()
            if task_id in self.downloaders:
                del self.downloaders[task_id]
            self.save_tasks()

        if self.on_task_updated:
            self.on_task_updated(task)

    def _handle_error(self, task_id: str, error: Exception):
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task.status = DownloadStatus.FAILED.value
            task.error_message = str(error)
            task.speed_bps = 0.0
            if task_id in self.downloaders:
                del self.downloaders[task_id]
            self.save_tasks()

        if self.on_task_updated:
            self.on_task_updated(task)

    def pause_task(self, task_id: str):
        with self._lock:
            downloader = self.downloaders.get(task_id)
            if downloader:
                if hasattr(downloader, "pause"):
                    downloader.pause()
                elif hasattr(downloader, "cancel"):
                    downloader.cancel()
                del self.downloaders[task_id]
            task = self.tasks.get(task_id)
            if task and task.status != DownloadStatus.COMPLETED.value:
                task.status = DownloadStatus.PAUSED.value
                task.speed_bps = 0.0
                self.save_tasks()

        if task and self.on_task_updated:
            self.on_task_updated(task)

    def resume_task(self, task_id: str):
        self.start_task(task_id)

    def cancel_task(self, task_id: str, remove_file: bool = False):
        with self._lock:
            downloader = self.downloaders.get(task_id)
            if downloader:
                if hasattr(downloader, "cancel"):
                    try:
                        downloader.cancel(remove_files=remove_file)
                    except TypeError:
                        downloader.cancel()
                del self.downloaders[task_id]

            task = self.tasks.get(task_id)
            if task:
                task.status = DownloadStatus.CANCELLED.value
                task.speed_bps = 0.0
                if remove_file and os.path.exists(task.output_path):
                    try:
                        os.remove(task.output_path)
                    except Exception:
                        pass
                self.save_tasks()

        if task and self.on_task_updated:
            self.on_task_updated(task)

    def delete_task(self, task_id: str, delete_file: bool = False):
        with self._lock:
            self.cancel_task(task_id, remove_file=delete_file)
            task = self.tasks.pop(task_id, None)
            if delete_file and task and os.path.exists(task.output_path):
                try:
                    os.remove(task.output_path)
                except Exception:
                    pass
            self.save_tasks()

        if self.on_task_removed:
            self.on_task_removed(task_id)

    def pause_all(self):
        with self._lock:
            active_ids = list(self.downloaders.keys())
        for task_id in active_ids:
            self.pause_task(task_id)

    def resume_all(self):
        with self._lock:
            paused_ids = [
                task.id for task in self.tasks.values()
                if task.status in (DownloadStatus.PAUSED.value, DownloadStatus.PENDING.value)
            ]
        for task_id in paused_ids:
            self.resume_task(task_id)

    def get_all_tasks(self) -> List[DownloadTask]:
        with self._lock:
            return list(self.tasks.values())

    def get_active_speed(self) -> float:
        with self._lock:
            return sum(getattr(d, "current_speed_bps", 0.0) for d in self.downloaders.values())

