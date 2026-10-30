"""
High-Performance Asynchronous Storage Manager for Internet Downloader.
Decouples network socket reads from disk writes using a dedicated background writer queue.
Completely eliminates thread lock contention and TCP buffer stalls on Windows.
"""

import os
import queue
import threading
import time
from typing import Optional


class AsyncDiskWriter:
    """
    Dedicated background disk writer that drains chunks from memory queue to disk.
    Allows network threads to run at 100% line rate without blocking on file locks.
    """
    def __init__(self, file_path: str, file_size: int, queue_size: int = 256):
        self.file_path = file_path
        self.file_size = file_size
        self._queue = queue.Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._file_handle = None
        self.total_bytes_written = 0

    def start(self, preallocate: bool = True):
        dir_name = os.path.dirname(os.path.abspath(self.file_path))
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

        # Pre-allocate sparse file if needed
        if not os.path.exists(self.file_path) or os.path.getsize(self.file_path) != self.file_size:
            with open(self.file_path, "wb") as f:
                if self.file_size > 0 and preallocate:
                    f.seek(self.file_size - 1)
                    f.write(b"\0")

        # Open in binary read-write mode with large 1MB buffer
        self._file_handle = open(self.file_path, "r+b", buffering=1024 * 1024)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()

    def write_chunk(self, offset: int, data: bytes, timeout: float = 5.0):
        """Pushes chunk to memory queue. Non-blocking unless memory queue fills up."""
        try:
            self._queue.put((offset, data), timeout=timeout)
        except queue.Full:
            # If disk is slow, briefly backpressure network thread
            self._queue.put((offset, data))

    def _writer_loop(self):
        batch = []
        last_flush = time.monotonic()

        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.05)
                if item is None:
                    break

                offset, data = item
                self._file_handle.seek(offset)
                self._file_handle.write(data)
                self.total_bytes_written += len(data)
                self._queue.task_done()

                # Periodic flush every 1 second
                now = time.monotonic()
                if now - last_flush > 1.0:
                    self._file_handle.flush()
                    last_flush = now

            except queue.Empty:
                if self._file_handle:
                    self._file_handle.flush()
            except Exception as e:
                print(f"Disk write error: {e}")

    def close(self):
        self._stop_event.set()
        try:
            self._queue.put(None, timeout=0.5)
        except Exception:
            pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        if self._file_handle and not self._file_handle.closed:
            try:
                self._file_handle.flush()
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None

    def finalize(self, state_file_path: Optional[str] = None):
        self.close()
        if state_file_path and os.path.exists(state_file_path):
            try:
                os.remove(state_file_path)
            except OSError:
                pass


# Backward compatible alias
StorageManager = AsyncDiskWriter

