"""
YouTube & Streaming Media Extraction Engine for Internet Downloader.
Integrates yt-dlp to resolve video metadata, thumbnails, and direct video streams.
"""

import os
import re
import threading
from typing import Optional, Callable, Dict, Any


def is_youtube_or_streaming_url(url: str) -> bool:
    """Checks if a URL points to YouTube or popular streaming platforms."""
    lower = url.lower()
    patterns = [
        "youtube.com/watch",
        "youtube.com/shorts",
        "youtu.be/",
        "m.youtube.com",
        "youtube.com/embed",
        "vimeo.com",
        "dailymotion.com",
        "twitch.tv",
        "tiktok.com"
    ]
    return any(p in lower for p in patterns)


def sanitize_filename(name: str) -> str:
    """Sanitizes filename for Windows filesystems."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def probe_youtube_video(url: str) -> Dict[str, Any]:
    """
    Extracts video title, approximate size, and metadata without downloading.
    """
    try:
        import yt_dlp
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            raw_title = info.get('title', 'YouTube_Video')
            clean_title = f"{sanitize_filename(raw_title)}.mp4"
            duration = info.get('duration', 0)
            thumbnail = info.get('thumbnail', '')
            file_size = info.get('filesize') or info.get('filesize_approx') or (duration * 250000)

            return {
                "success": True,
                "title": clean_title,
                "file_size": int(file_size),
                "duration": duration,
                "thumbnail": thumbnail,
                "is_youtube": True
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "title": "YouTube_Video.mp4",
            "file_size": 0,
            "is_youtube": True
        }


class YouTubeDownloaderWorker:
    """
    Worker that executes yt-dlp download in a background thread
    and delivers real-time progress callbacks to the UI.
    """
    def __init__(
        self,
        url: str,
        output_path: str,
        on_progress: Optional[Callable[[float, int, int, float, float], None]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ):
        self.url = url
        self.output_path = output_path
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error
        self._stop_event = threading.Event()
        self.current_speed_bps = 0.0
        self.eta_seconds = 0.0
        self.total_downloaded = 0
        self.file_size = 0

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self._stop_event.set()

    def _progress_hook(self, d: dict):
        if self._stop_event.is_set():
            raise Exception("Download cancelled by user")

        status = d.get('status')
        if status == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            speed = d.get('speed') or 0.0
            eta = d.get('eta') or 0.0

            self.file_size = total
            self.total_downloaded = downloaded
            self.current_speed_bps = speed
            self.eta_seconds = eta

            pct = (downloaded / total * 100.0) if total > 0 else 0.0

            if self.on_progress:
                self.on_progress(pct, downloaded, total, speed, eta)

        elif status == 'finished':
            self.total_downloaded = self.file_size

    def _run(self):
        try:
            import yt_dlp

            # Prepare directory and template
            out_dir = os.path.dirname(os.path.abspath(self.output_path))
            os.makedirs(out_dir, exist_ok=True)

            base_name = os.path.splitext(os.path.basename(self.output_path))[0]
            out_tmpl = os.path.join(out_dir, f"{base_name}.%(ext)s")

            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': out_tmpl,
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [self._progress_hook]
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])

            if self.on_complete:
                self.on_complete(self.output_path)
        except Exception as e:
            if not self._stop_event.is_set():
                if self.on_error:
                    self.on_error(e)

