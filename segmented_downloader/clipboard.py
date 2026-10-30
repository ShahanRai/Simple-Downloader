"""
Windows Clipboard Monitor for IDM Downloader.
Watches system clipboard for downloadable URLs and notifies GUI.
"""

import time
import threading
import re
from typing import Optional, Callable

# Extensions commonly intercepted by IDM
DOWNLOAD_EXTENSIONS = (
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".iso", ".dmg",
    ".exe", ".msi", ".apk", ".bin",
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv",
    ".mp3", ".wav", ".flac", ".aac", ".opus",
    ".pdf", ".epub", ".docx", ".xlsx", ".pptx"
)


class ClipboardMonitor:
    def __init__(self, on_url_detected: Callable[[str], None]):
        self.on_url_detected = on_url_detected
        self.enabled = False
        self._thread: Optional[threading.Thread] = None
        self._last_clipboard_text = ""

    def start(self):
        self.enabled = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.enabled = False

    def _loop(self):
        while self.enabled:
            time.sleep(0.8)
            try:
                text = self._get_clipboard_text()
                if text and text != self._last_clipboard_text:
                    self._last_clipboard_text = text
                    cleaned = text.strip()
                    if self._is_downloadable_url(cleaned):
                        self.on_url_detected(cleaned)
            except Exception:
                pass

    def _is_downloadable_url(self, text: str) -> bool:
        if not (text.startswith("http://") or text.startswith("https://") or text.startswith("ftp://")):
            return False

        if " " in text or "\n" in text:
            return False

        lower = text.lower().split("?")[0].split("#")[0]
        if any(lower.endswith(ext) for ext in DOWNLOAD_EXTENSIONS):
            return True

        # Catch common file hosting patterns
        if any(host in lower for host in ["mediafire.com", "mega.nz", "drive.google.com/file", "github.com/releases"]):
            return True

        return False

    def _get_clipboard_text(self) -> str:
        try:
            import win32clipboard
            import win32con

            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    return data
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            pass
        return ""

