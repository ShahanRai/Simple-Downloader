"""
Core High-Performance Segmented Downloader Engine for Internet Downloader.
Implements multi-threaded concurrent range requests, persistent HTTP connection pooling,
IDM-style dynamic segment splitting, asynchronous zero-contention disk writes,
and Exponential Moving Average (EMA) speed smoothing.
"""

from dataclasses import dataclass
from typing import Optional, Callable, List
import threading
import time
import os
import urllib3

from .model import Segment, DownloadMetadata, DownloadStatus, SegmentStatus
from .storage import AsyncDiskWriter
from .speed_limiter import SpeedLimiter
from .protocol import probe_url, ProbeResult, DEFAULT_USER_AGENT


@dataclass
class DownloadConfig:
    connections: int = 8
    chunk_size: int = 262144  # 256 KB high-throughput buffer (matching IDM)
    max_speed_bps: float = 0.0  # 0 = unlimited
    dynamic_split: bool = True
    min_split_size: int = 4 * 1024 * 1024  # 4 MB minimum to justify splitting
    user_agent: str = DEFAULT_USER_AGENT
    timeout: int = 30


class SegmentedDownloader:
    """
    High-Performance Multipart Download Engine.
    Uses connection pooling, non-blocking asynchronous disk writes,
    dynamic segment re-balancing, and EMA speed smoothing.
    """

    def __init__(
        self,
        url: str,
        output_path: Optional[str] = None,
        config: Optional[DownloadConfig] = None,
        on_progress: Optional[Callable[["SegmentedDownloader"], None]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ):
        self.url = url
        self.config = config or DownloadConfig()
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error

        self.metadata: Optional[DownloadMetadata] = None
        self.storage: Optional[AsyncDiskWriter] = None
        self.limiter = SpeedLimiter(self.config.max_speed_bps)

        self.output_path = output_path
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._lock = threading.Lock()
        self._workers: List[threading.Thread] = []

        # Persistent connection pool with keep-alive
        self._http_pool = urllib3.PoolManager(
            maxsize=max(32, self.config.connections * 2),
            timeout=urllib3.Timeout(connect=15.0, read=self.config.timeout),
            retries=urllib3.Retry(total=3, backoff_factor=0.5)
        )

        # Smooth EMA speed calculation
        self._last_speed_check = time.monotonic()
        self._last_downloaded_bytes = 0
        self.current_speed_bps = 0.0
        self.eta_seconds = 0.0
        self.error: Optional[Exception] = None

    def start(self, wait: bool = False):
        """Starts or resumes the download."""
        self._stop_event.clear()
        self._pause_event.clear()

        # Step 1: Probe server and set up metadata
        probe = probe_url(self.url, user_agent=self.config.user_agent, timeout=self.config.timeout)

        # Ensure output directory & filename are properly resolved in Downloads
        if not self.output_path:
            downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(downloads_dir, exist_ok=True)
            self.output_path = os.path.join(downloads_dir, probe.filename)
        elif os.path.isdir(self.output_path):
            os.makedirs(self.output_path, exist_ok=True)
            self.output_path = os.path.join(self.output_path, probe.filename)
        else:
            parent_dir = os.path.dirname(os.path.abspath(self.output_path))
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

        state_file = f"{self.output_path}.state.json"
        existing_meta = DownloadMetadata.load(state_file)

        if existing_meta and existing_meta.url == self.url and existing_meta.file_size == probe.file_size:
            if (probe.etag and existing_meta.etag and probe.etag != existing_meta.etag) or \
               (probe.last_modified and existing_meta.last_modified and probe.last_modified != existing_meta.last_modified):
                self.metadata = self._initialize_metadata(probe)
            else:
                self.metadata = existing_meta
                self.metadata.status = DownloadStatus.DOWNLOADING
        else:
            self.metadata = self._initialize_metadata(probe)

        # Initialize asynchronous zero-contention disk writer
        self.storage = AsyncDiskWriter(self.output_path, self.metadata.file_size)
        self.storage.start(preallocate=self.metadata.accepts_ranges)
        self.metadata.status = DownloadStatus.DOWNLOADING
        self.metadata.save()

        # Reset speed tracking
        self._last_speed_check = time.monotonic()
        self._last_downloaded_bytes = self.metadata.total_downloaded
        self.current_speed_bps = 0.0

        # Step 2: Spawn worker threads
        runner_thread = threading.Thread(target=self._run_download, daemon=True)
        runner_thread.start()

        if wait:
            runner_thread.join()

    def pause(self):
        """Pauses the download and saves state."""
        self._pause_event.set()
        if self.metadata:
            self.metadata.status = DownloadStatus.PAUSED
            self.metadata.save()
        if self.storage:
            self.storage.close()

    def cancel(self, remove_files: bool = True):
        """Cancels download and optionally purges files from disk."""
        self._stop_event.set()
        if self.storage:
            self.storage.close()
        if self.metadata:
            self.metadata.status = DownloadStatus.CANCELLED
            if os.path.exists(self.metadata.state_path):
                try:
                    os.remove(self.metadata.state_path)
                except OSError:
                    pass

        if remove_files and self.output_path and os.path.exists(self.output_path):
            try:
                os.remove(self.output_path)
            except OSError:
                pass

    def _initialize_metadata(self, probe: ProbeResult) -> DownloadMetadata:
        segments = []
        if probe.accepts_ranges and probe.file_size > 0:
            num_conns = min(self.config.connections, max(1, probe.file_size // self.config.min_split_size))
            num_conns = max(1, num_conns)
            part_size = probe.file_size // num_conns

            for i in range(num_conns):
                start = i * part_size
                end = (i + 1) * part_size - 1 if i < num_conns - 1 else probe.file_size - 1
                segments.append(Segment(
                    id=i,
                    start_byte=start,
                    end_byte=end,
                    current_byte=start,
                    status=SegmentStatus.PENDING
                ))
        else:
            segments.append(Segment(
                id=0,
                start_byte=0,
                end_byte=probe.file_size - 1 if probe.file_size > 0 else 0,
                current_byte=0,
                status=SegmentStatus.PENDING
            ))

        return DownloadMetadata(
            url=probe.final_url,
            output_path=self.output_path,
            file_size=probe.file_size,
            accepts_ranges=probe.accepts_ranges,
            etag=probe.etag,
            last_modified=probe.last_modified,
            status=DownloadStatus.DOWNLOADING,
            segments=segments,
            created_at=time.time()
        )

    def _run_download(self):
        """Coordinates segment download workers and monitors progress."""
        try:
            self._workers = []
            for segment in self.metadata.segments:
                if segment.remaining_bytes > 0:
                    t = threading.Thread(target=self._worker_loop, args=(segment,), daemon=True)
                    self._workers.append(t)
                    t.start()

            # Main monitor loop
            while not self._stop_event.is_set() and not self._pause_event.is_set():
                time.sleep(0.2)
                self._update_speed()

                if self.config.dynamic_split and self.metadata.accepts_ranges:
                    self._try_dynamic_split()

                if self.on_progress:
                    self.on_progress(self)

                all_done = all(s.remaining_bytes <= 0 for s in self.metadata.segments)
                if all_done:
                    break

            for t in self._workers:
                t.join(timeout=0.5)

            is_complete = all(s.remaining_bytes <= 0 for s in self.metadata.segments) or \
                          (self.metadata.total_downloaded >= self.metadata.file_size and self.metadata.file_size > 0)

            if is_complete:
                self.metadata.status = DownloadStatus.COMPLETED
                self.storage.finalize(self.metadata.state_path)
                if os.path.exists(self.metadata.state_path):
                    try:
                        os.remove(self.metadata.state_path)
                    except OSError:
                        pass
                if self.on_complete:
                    self.on_complete(self.output_path)
            elif self._pause_event.is_set():
                self.metadata.status = DownloadStatus.PAUSED
                self.metadata.save()
                self.storage.close()

        except Exception as e:
            self.error = e
            if self.metadata:
                self.metadata.status = DownloadStatus.FAILED
                self.metadata.save()
            if self.on_error:
                self.on_error(e)

    def _worker_loop(self, segment: Segment):
        """Worker thread executing HTTP Range requests using connection pool."""
        segment.status = SegmentStatus.DOWNLOADING
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "*/*",
            "Connection": "keep-alive"
        }

        while segment.remaining_bytes > 0 and not self._stop_event.is_set() and not self._pause_event.is_set():
            if self.metadata.accepts_ranges:
                headers["Range"] = f"bytes={segment.current_byte}-{segment.end_byte}"

            try:
                # Use connection pool for persistent TCP streams
                resp = self._http_pool.request(
                    "GET",
                    self.metadata.url,
                    headers=headers,
                    preload_content=False
                )

                chunk_size = self.config.chunk_size
                while not self._stop_event.is_set() and not self._pause_event.is_set():
                    to_read = min(chunk_size, segment.remaining_bytes)
                    if to_read <= 0:
                        break

                    chunk = resp.read(to_read)
                    if not chunk:
                        break

                    # Write asynchronously to background disk queue (ZERO lock contention)
                    self.storage.write_chunk(segment.current_byte, chunk)
                    chunk_len = len(chunk)
                    segment.current_byte += chunk_len

                    # Apply speed limiter
                    self.limiter.consume(chunk_len)

                resp.release_conn()

            except Exception:
                if self._stop_event.is_set() or self._pause_event.is_set():
                    break
                time.sleep(0.5)

        if segment.remaining_bytes <= 0:
            segment.status = SegmentStatus.COMPLETED
        elif self._pause_event.is_set():
            segment.status = SegmentStatus.PAUSED

    def _try_dynamic_split(self):
        """
        IDM Signature Feature: Dynamic Segmentation.
        Splits remaining bytes of the slowest thread in half when capacity allows.
        """
        with self._lock:
            active_segments = [s for s in self.metadata.segments if s.status == SegmentStatus.DOWNLOADING]
            if len(active_segments) >= self.config.connections:
                return

            largest = None
            max_remaining = 0
            for s in active_segments:
                if s.remaining_bytes > max_remaining:
                    max_remaining = s.remaining_bytes
                    largest = s

            if not largest or max_remaining < (self.config.min_split_size * 2):
                return

            current = largest.current_byte
            end = largest.end_byte
            midpoint = current + (end - current) // 2

            largest.end_byte = midpoint

            new_id = len(self.metadata.segments)
            new_segment = Segment(
                id=new_id,
                start_byte=midpoint + 1,
                end_byte=end,
                current_byte=midpoint + 1,
                status=SegmentStatus.PENDING
            )
            self.metadata.segments.append(new_segment)

            t = threading.Thread(target=self._worker_loop, args=(new_segment,), daemon=True)
            self._workers.append(t)
            t.start()

    def _update_speed(self):
        """
        Calculates speed using Exponential Moving Average (EMA).
        Completely eliminates wild spikes and drops for consistent IDM-like measurement.
        """
        now = time.monotonic()
        elapsed = now - self._last_speed_check
        if elapsed >= 0.2:
            current_bytes = self.metadata.total_downloaded
            delta = current_bytes - self._last_downloaded_bytes
            instant_speed = max(0.0, delta / elapsed)

            # EMA smoothing: 30% new sample, 70% historical average
            if self.current_speed_bps == 0.0:
                self.current_speed_bps = instant_speed
            else:
                self.current_speed_bps = (0.35 * instant_speed) + (0.65 * self.current_speed_bps)

            self._last_downloaded_bytes = current_bytes
            self._last_speed_check = now

            if self.current_speed_bps > 0 and self.metadata.file_size > 0:
                remaining = max(0, self.metadata.file_size - current_bytes)
                self.eta_seconds = remaining / self.current_speed_bps
            else:
                self.eta_seconds = 0.0

