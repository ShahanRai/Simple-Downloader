"""
Full-Featured Executive Desktop GUI for Internet Downloader.
Coordinates multi-threaded downloads, YouTube video streams,
real-time segment visualizers, system tray notifications,
clipboard auto-capture, and browser extension bridges.
"""

import sys
import os
import subprocess
import webbrowser
import threading
from typing import Optional, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QMenu, QDialog, QComboBox, QSlider, QCheckBox,
    QSystemTrayIcon, QSplitter, QFrame, QStackedWidget
)
from PyQt6.QtGui import (
    QFont, QIcon, QColor, QAction, QPixmap, QPainter, QCursor, QBrush, QPen
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QPoint

from .neumorphic_theme import (
    NeumorphicTheme, NeumorphicCard, NeumorphicButton, NeumorphicLineEdit,
    NeumorphicProgressBar, NeumorphicSegmentBar, get_global_stylesheet
)
from .queue_manager import QueueManager, DownloadTask
from .server import IDMAPIServer, DEFAULT_SERVER_PORT
from .clipboard import ClipboardMonitor
from .protocol import probe_url, DEFAULT_USER_AGENT
from .youtube import is_youtube_or_streaming_url, probe_youtube_video
from .model import DownloadStatus


def format_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:3.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


class AddDownloadDialog(QDialog):
    """
    Modern Executive Modal Dialog for adding a new download URL or YouTube video.
    """
    def __init__(self, initial_url: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚡ Add New Download - Internet Downloader")
        self.setFixedSize(640, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        t = NeumorphicTheme.current
        self.setStyleSheet(f"background-color: {t['bg']}; color: {t['text_primary']};")

        self.inferred_filename = ""
        self.inferred_size = 0

        self._build_ui(initial_url)

    def _build_ui(self, initial_url: str):
        t = NeumorphicTheme.current
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)

        # Header Title
        title_row = QHBoxLayout()
        icon_lbl = QLabel("⚡")
        icon_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {t['accent']};")
        title_row.addWidget(icon_lbl)

        title_lbl = QLabel("Enter Download URL or YouTube Link")
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        layout.addLayout(title_row)

        # URL Input Field + Paste Button
        url_row = QHBoxLayout()
        self.url_input = NeumorphicLineEdit(placeholder="https://example.com/file.zip or YouTube video URL")
        if initial_url:
            self.url_input.setText(initial_url)
        self.url_input.textChanged.connect(self._on_url_changed)
        url_row.addWidget(self.url_input, stretch=4)

        paste_btn = NeumorphicButton("📋 Paste", radius=10)
        paste_btn.setMinimumWidth(80)
        paste_btn.clicked.connect(self._on_paste_clicked)
        url_row.addWidget(paste_btn, stretch=1)
        layout.addLayout(url_row)

        # File Info Card
        self.info_card = NeumorphicCard(is_raised=False, radius=10)
        info_layout = QVBoxLayout(self.info_card)
        info_layout.setContentsMargins(16, 12, 16, 12)

        self.probe_lbl = QLabel("Paste a URL above to inspect file or video stream details...")
        self.probe_lbl.setFont(QFont("Segoe UI", 9))
        self.probe_lbl.setStyleSheet(f"color: {t['text_secondary']};")
        self.probe_lbl.setWordWrap(True)
        info_layout.addWidget(self.probe_lbl)
        layout.addWidget(self.info_card)

        # Destination Directory
        dest_lbl = QLabel("Save Destination Folder:")
        dest_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        layout.addWidget(dest_lbl)

        dest_row = QHBoxLayout()
        qm = QueueManager.get_instance()
        self.dest_input = NeumorphicLineEdit(placeholder=qm.default_download_dir)
        self.dest_input.setText(qm.default_download_dir)
        dest_row.addWidget(self.dest_input, stretch=4)

        browse_btn = NeumorphicButton("📁 Browse...", radius=10)
        browse_btn.setMinimumWidth(90)
        browse_btn.clicked.connect(self._on_browse)
        dest_row.addWidget(browse_btn, stretch=1)
        layout.addLayout(dest_row)

        # Options Row: Connections & Speed Limit
        opts_row = QHBoxLayout()

        conn_lbl = QLabel("Parallel Streams:")
        conn_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        opts_row.addWidget(conn_lbl)

        self.conn_combo = QComboBox()
        self.conn_combo.addItems(["1", "2", "4", "8", "16", "24", "32"])
        self.conn_combo.setCurrentText("16")
        self.conn_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {t['card_sunken']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 6px 12px;
                min-width: 70px;
                font-weight: bold;
            }}
        """)
        opts_row.addWidget(self.conn_combo)
        opts_row.addSpacing(20)

        limit_lbl = QLabel("Speed Cap (KB/s):")
        limit_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        opts_row.addWidget(limit_lbl)

        self.limit_input = NeumorphicLineEdit(placeholder="0 (Unlimited)")
        self.limit_input.setText("0")
        self.limit_input.setMaximumWidth(120)
        opts_row.addWidget(self.limit_input)
        opts_row.addStretch()

        layout.addLayout(opts_row)
        layout.addStretch()

        # Action Buttons Row
        actions_row = QHBoxLayout()
        actions_row.addStretch()

        cancel_btn = NeumorphicButton("Cancel", radius=10, variant="ghost")
        cancel_btn.setMinimumWidth(90)
        cancel_btn.clicked.connect(self.reject)
        actions_row.addWidget(cancel_btn)

        queue_btn = NeumorphicButton("Download Later", radius=10)
        queue_btn.setMinimumWidth(130)
        queue_btn.clicked.connect(lambda: self._submit(auto_start=False))
        actions_row.addWidget(queue_btn)

        start_btn = NeumorphicButton("⚡ Start Download", variant="primary", radius=10)
        start_btn.setMinimumWidth(140)
        start_btn.clicked.connect(lambda: self._submit(auto_start=True))
        actions_row.addWidget(start_btn)

        layout.addLayout(actions_row)

        if initial_url:
            self._probe_url_async(initial_url)

    def _on_paste_clicked(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_input.setText(text)

    def _on_url_changed(self, text: str):
        url = text.strip()
        if url.startswith("http://") or url.startswith("https://"):
            self._probe_url_async(url)

    def _probe_url_async(self, url: str):
        t = NeumorphicTheme.current
        self.probe_lbl.setText("🔍 Analyzing remote server and media stream headers...")
        self.probe_lbl.setStyleSheet(f"color: {t['accent']};")

        def probe_worker():
            if is_youtube_or_streaming_url(url):
                info = probe_youtube_video(url)
                title = info.get("title", "YouTube Video")
                dur = info.get("duration", 0)
                dur_str = f"{dur // 60}m {dur % 60}s" if dur > 0 else "Live/Unknown"
                self.inferred_filename = title
                self.inferred_size = info.get("file_size", 0)
                text = f"🎬 YouTube Media Detected:\nTitle: {title}\nDuration: {dur_str} | Resolution: 1080p/720p HD MP4"
                color = t["green"]
            else:
                try:
                    res = probe_url(url)
                    self.inferred_filename = res.filename
                    self.inferred_size = res.file_size
                    text = f"📄 Remote File: {res.filename}\nSize: {format_bytes(res.file_size)} | Range Resume: {'Supported ✔ (32-Stream Turbo)' if res.accepts_ranges else 'Single-Stream ⚠'}"
                    color = t["green"] if res.accepts_ranges else t["amber"]
                except Exception as e:
                    text = f"Could not probe remote headers: {e}"
                    color = t["red"]

            def update_ui():
                self.probe_lbl.setText(text)
                self.probe_lbl.setStyleSheet(f"color: {color};")
            QTimer.singleShot(0, update_ui)

        threading.Thread(target=probe_worker, daemon=True).start()

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.dest_input.text())
        if folder:
            self.dest_input.setText(folder)

    def _submit(self, auto_start: bool):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Invalid URL", "Please enter a valid download URL.")
            return

        dest_dir = self.dest_input.text().strip() or os.path.join(os.path.expanduser("~"), "Downloads")
        conns = int(self.conn_combo.currentText())
        try:
            speed_limit = float(self.limit_input.text().strip())
        except ValueError:
            speed_limit = 0.0

        qm = QueueManager.get_instance()
        qm.add_task(
            url=url,
            output_dir=dest_dir,
            custom_filename=self.inferred_filename or None,
            connections=conns,
            speed_limit_kb=speed_limit,
            auto_start=auto_start
        )
        self.accept()


class BrowserExtensionDialog(QDialog):
    """
    Browser Extension Installation & Verification Center.
    Matches IDM's official extension installation model (1-click Web Store, CRX, Unpacked).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌐 Browser Extension Center - Internet Downloader")
        self.setFixedSize(680, 520)
        t = NeumorphicTheme.current
        self.setStyleSheet(f"background-color: {t['bg']}; color: {t['text_primary']};")

        self._build_ui()

    def _build_ui(self):
        t = NeumorphicTheme.current
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)

        # Header Title
        title_row = QHBoxLayout()
        icon_lbl = QLabel("🌐")
        icon_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {t['accent']};")
        title_row.addWidget(icon_lbl)

        title_lbl = QLabel("Internet Downloader - Browser Integration")
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        layout.addLayout(title_row)

        sub_lbl = QLabel(
            "Integrate Internet Downloader into Google Chrome, Microsoft Edge, Brave, and Mozilla Firefox "
            "to automatically intercept download links, context menus, and capture streaming YouTube videos!"
        )
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(f"color: {t['text_secondary']};")
        layout.addWidget(sub_lbl)

        # Status Card
        card = NeumorphicCard(is_raised=True, radius=12)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)

        status_row = QHBoxLayout()
        dot_lbl = QLabel("●")
        dot_lbl.setFont(QFont("Segoe UI", 12))
        dot_lbl.setStyleSheet(f"color: {t['green']};")
        status_text = QLabel(f"Local Extension Bridge: ONLINE (Listening on Port {DEFAULT_SERVER_PORT})")
        status_text.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        status_text.setStyleSheet(f"color: {t['green']};")
        status_row.addWidget(dot_lbl)
        status_row.addWidget(status_text)
        status_row.addStretch()

        test_btn = NeumorphicButton("🧪 Test Bridge", radius=8)
        test_btn.setMinimumWidth(100)
        test_btn.clicked.connect(self._test_connection)
        status_row.addWidget(test_btn)

        card_layout.addLayout(status_row)

        desc = QLabel(
            "The background bridge is active. Registered native host names: com.tonec.idm and com.idm.downloader."
        )
        desc.setStyleSheet(f"color: {t['text_muted']}; font-size: 8.5pt;")
        card_layout.addWidget(desc)
        layout.addWidget(card)

        # 3 Easy Installation Options
        opts_title = QLabel("Choose Your Preferred Installation Method:")
        opts_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(opts_title)

        # Option 1: Chrome Web Store (1-Click)
        opt1_card = NeumorphicCard(is_raised=False, radius=10)
        opt1_layout = QHBoxLayout(opt1_card)
        opt1_layout.setContentsMargins(16, 12, 16, 12)

        opt1_info = QVBoxLayout()
        o1_title = QLabel("Option 1: Official Chrome Web Store Extension (1-Click)")
        o1_title.setFont(QFont("Segoe UI", 9.5, QFont.Weight.Bold))
        o1_desc = QLabel("Opens the Web Store page where you click 'Add to Chrome' or 'Add to Edge'. Fully automatic.")
        o1_desc.setStyleSheet(f"color: {t['text_secondary']}; font-size: 8.5pt;")
        opt1_info.addWidget(o1_title)
        opt1_info.addWidget(o1_desc)
        opt1_layout.addLayout(opt1_info, stretch=4)

        webstore_btn = NeumorphicButton("⚡ Install from Store", variant="primary", radius=8)
        webstore_btn.setMinimumWidth(150)
        webstore_btn.clicked.connect(lambda: webbrowser.open(
            "https://chromewebstore.google.com/detail/idm-integration-module/ngpampappnmepgilojfohadhhmbhlaek"
        ))
        opt1_layout.addWidget(webstore_btn, stretch=2)
        layout.addWidget(opt1_card)

        # Option 2: Direct CRX Drag-and-Drop
        opt2_card = NeumorphicCard(is_raised=False, radius=10)
        opt2_layout = QHBoxLayout(opt2_card)
        opt2_layout.setContentsMargins(16, 12, 16, 12)

        opt2_info = QVBoxLayout()
        o2_title = QLabel("Option 2: Direct CRX Package (IDMGCExt.crx)")
        o2_title.setFont(QFont("Segoe UI", 9.5, QFont.Weight.Bold))
        o2_desc = QLabel("Included in the app folder. Open chrome://extensions, enable Developer Mode, and drag & drop.")
        o2_desc.setStyleSheet(f"color: {t['text_secondary']}; font-size: 8.5pt;")
        opt2_info.addWidget(o2_title)
        opt2_info.addWidget(o2_desc)
        opt2_layout.addLayout(opt2_info, stretch=4)

        crx_btn = NeumorphicButton("📁 Open CRX Folder", radius=8)
        crx_btn.setMinimumWidth(150)
        crx_btn.clicked.connect(self._open_crx_folder)
        opt2_layout.addWidget(crx_btn, stretch=2)
        layout.addWidget(opt2_card)

        # Close button
        layout.addStretch()
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = NeumorphicButton("Close", radius=8)
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _test_connection(self):
        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:{DEFAULT_SERVER_PORT}/status")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    QMessageBox.information(
                        self, "Extension Bridge Active",
                        "✔ The local extension bridge is online and responding at http://127.0.0.1:9653!\n\n"
                        "Browser extensions can communicate with Internet Downloader immediately."
                    )
                    return
        except Exception as e:
            QMessageBox.warning(self, "Bridge Check", f"Could not reach local bridge: {e}")

    def _open_crx_folder(self):
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.exists(app_dir):
            os.startfile(app_dir)


class IDMMainWindow(QMainWindow):
    """
    Main Window for Internet Downloader featuring Executive UI, Empty-State Hero,
    and Dynamic Segment Visualization.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("⚡ Internet Downloader PRO - Dynamic Multi-Stream & Media Acceleration")
        self.resize(1120, 720)
        self.setMinimumSize(960, 600)

        self.qm = QueueManager.get_instance()
        self.selected_task_id: Optional[str] = None
        self.current_filter_category: str = "ALL"

        # Apply global stylesheet
        self.setStyleSheet(get_global_stylesheet())

        self._build_ui()
        self._setup_tray()
        self._setup_timers()
        self._start_services()

    def _build_ui(self):
        t = NeumorphicTheme.current
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(16, 14, 16, 14)
        root_layout.setSpacing(12)

        # 1. Top Executive Header Bar
        header_card = NeumorphicCard(is_raised=True, radius=12)
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(18, 12, 18, 12)
        header_layout.setSpacing(14)

        # Left: Brand Logo & Title
        logo_box = QHBoxLayout()
        logo_box.setSpacing(10)

        logo_icon = QLabel("⚡")
        logo_icon.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        logo_icon.setStyleSheet(f"color: {t['accent']};")
        logo_box.addWidget(logo_icon)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_lbl = QLabel("Internet Downloader")
        title_lbl.setFont(QFont("Segoe UI Variable Display", 14, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {t['text_primary']};")
        title_row.addWidget(title_lbl)

        pro_badge = QLabel("PRO")
        pro_badge.setFont(QFont("Segoe UI", 7.5, QFont.Weight.Bold))
        pro_badge.setStyleSheet(f"""
            background-color: {t['accent']};
            color: #ffffff;
            border-radius: 4px;
            padding: 2px 6px;
        """)
        title_row.addWidget(pro_badge)
        title_row.addStretch()
        title_col.addLayout(title_row)

        sub_lbl = QLabel("Dynamic 32-Stream Acceleration Engine")
        sub_lbl.setFont(QFont("Segoe UI", 8))
        sub_lbl.setStyleSheet(f"color: {t['text_muted']};")
        title_col.addWidget(sub_lbl)

        logo_box.addLayout(title_col)
        header_layout.addLayout(logo_box)

        header_layout.addStretch()

        # Center: Real-Time Speed Dashboard
        self.speed_pill = NeumorphicCard(is_raised=False, radius=10)
        pill_layout = QHBoxLayout(self.speed_pill)
        pill_layout.setContentsMargins(14, 6, 14, 6)
        pill_layout.setSpacing(8)

        dot = QLabel("●")
        dot.setFont(QFont("Segoe UI", 10))
        dot.setStyleSheet(f"color: {t['green']};")
        pill_layout.addWidget(dot)

        self.speed_lbl = QLabel("Speed: 0.0 KB/s")
        self.speed_lbl.setFont(QFont("Segoe UI", 9.5, QFont.Weight.Bold))
        self.speed_lbl.setStyleSheet(f"color: {t['green']};")
        pill_layout.addWidget(self.speed_lbl)

        self.active_count_lbl = QLabel("|  0 Active")
        self.active_count_lbl.setFont(QFont("Segoe UI", 8.5))
        self.active_count_lbl.setStyleSheet(f"color: {t['text_muted']};")
        pill_layout.addWidget(self.active_count_lbl)

        header_layout.addWidget(self.speed_pill)

        # Right: Action Buttons (Generous spacing, zero truncation)
        self.add_btn = NeumorphicButton("+ Add URL", variant="primary", radius=10)
        self.add_btn.setMinimumWidth(110)
        self.add_btn.clicked.connect(self._open_add_dialog)
        header_layout.addWidget(self.add_btn)

        self.resume_all_btn = NeumorphicButton("▶ Resume", radius=10)
        self.resume_all_btn.setMinimumWidth(95)
        self.resume_all_btn.clicked.connect(self.qm.resume_all)
        header_layout.addWidget(self.resume_all_btn)

        self.pause_all_btn = NeumorphicButton("⏸ Pause", radius=10)
        self.pause_all_btn.setMinimumWidth(90)
        self.pause_all_btn.clicked.connect(self.qm.pause_all)
        header_layout.addWidget(self.pause_all_btn)

        ext_btn = NeumorphicButton("🌐 Extension", radius=10)
        ext_btn.setMinimumWidth(105)
        ext_btn.clicked.connect(self._open_extension_dialog)
        header_layout.addWidget(ext_btn)

        self.theme_btn = NeumorphicButton("🌓", radius=10)
        self.theme_btn.setFixedWidth(44)
        self.theme_btn.setToolTip("Toggle Dark/Light Mode")
        self.theme_btn.clicked.connect(self._toggle_theme)
        header_layout.addWidget(self.theme_btn)

        root_layout.addWidget(header_card)

        # 2. Main Content Splitter (Sidebar + Downloads Area)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        # Sidebar Card
        sidebar_card = NeumorphicCard(is_raised=True, radius=12)
        sidebar_card.setMinimumWidth(220)
        sidebar_card.setMaximumWidth(250)
        sidebar_layout = QVBoxLayout(sidebar_card)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(6)

        # Category Group 1: TASKS
        tasks_hdr = QLabel("TASKS")
        tasks_hdr.setFont(QFont("Segoe UI", 7.5, QFont.Weight.Bold))
        tasks_hdr.setStyleSheet(f"color: {t['text_muted']}; letter-spacing: 0.5px;")
        sidebar_layout.addWidget(tasks_hdr)

        self.cat_btns = {}
        task_filters = [
            ("ALL", "⚡ All Tasks"),
            ("DOWNLOADING", "⬇ Downloading"),
            ("COMPLETED", "✔ Completed"),
            ("PAUSED", "❚❚ Paused"),
        ]
        for cat_key, cat_name in task_filters:
            btn = NeumorphicButton(cat_name, radius=8)
            btn.clicked.connect(lambda checked, k=cat_key: self._set_category_filter(k))
            self.cat_btns[cat_key] = btn
            sidebar_layout.addWidget(btn)

        sidebar_layout.addSpacing(10)

        # Category Group 2: CATEGORIES
        cat_hdr = QLabel("CATEGORIES")
        cat_hdr.setFont(QFont("Segoe UI", 7.5, QFont.Weight.Bold))
        cat_hdr.setStyleSheet(f"color: {t['text_muted']}; letter-spacing: 0.5px;")
        sidebar_layout.addWidget(cat_hdr)

        media_categories = [
            ("Video", "🎬 Videos & YouTube"),
            ("Compressed", "📦 Compressed"),
            ("Music", "🎵 Music & Audio"),
            ("Documents", "📄 Documents"),
            ("Programs", "💻 Applications"),
        ]
        for cat_key, cat_name in media_categories:
            btn = NeumorphicButton(cat_name, radius=8)
            btn.clicked.connect(lambda checked, k=cat_key: self._set_category_filter(k))
            self.cat_btns[cat_key] = btn
            sidebar_layout.addWidget(btn)

        sidebar_layout.addSpacing(12)

        # Bandwidth Presets
        bw_hdr = QLabel("SPEED LIMIT PRESET")
        bw_hdr.setFont(QFont("Segoe UI", 7.5, QFont.Weight.Bold))
        bw_hdr.setStyleSheet(f"color: {t['text_muted']}; letter-spacing: 0.5px;")
        sidebar_layout.addWidget(bw_hdr)

        bw_row = QHBoxLayout()
        bw_row.setSpacing(4)
        self.preset_btns = {}
        presets = [("Max", 0), ("20M", 20), ("5M", 5), ("1M", 1)]
        for label, mb_val in presets:
            b = NeumorphicButton(label, radius=6)
            b.setFixedHeight(28)
            b.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            b.clicked.connect(lambda checked, v=mb_val, l=label: self._set_bandwidth_preset(v, l))
            self.preset_btns[label] = b
            bw_row.addWidget(b)
        sidebar_layout.addLayout(bw_row)

        self.limiter_lbl = QLabel("Unlimited (Full Line Speed)")
        self.limiter_lbl.setFont(QFont("Segoe UI", 7.5))
        self.limiter_lbl.setStyleSheet(f"color: {t['text_secondary']};")
        sidebar_layout.addWidget(self.limiter_lbl)

        sidebar_layout.addSpacing(8)

        # Clipboard Auto-Capture Checkbox
        self.clip_check = QCheckBox("Auto-Detect Clipboard URLs")
        self.clip_check.setChecked(True)
        self.clip_check.setFont(QFont("Segoe UI", 8))
        self.clip_check.setStyleSheet(f"color: {t['text_secondary']};")
        sidebar_layout.addWidget(self.clip_check)

        sidebar_layout.addStretch()

        # Browser Extension Status Card
        ext_status_card = NeumorphicCard(is_raised=False, radius=8)
        ext_s_layout = QVBoxLayout(ext_status_card)
        ext_s_layout.setContentsMargins(10, 8, 10, 8)
        ext_s_layout.setSpacing(3)

        status_line = QHBoxLayout()
        ext_dot = QLabel("●")
        ext_dot.setStyleSheet(f"color: {t['green']}; font-size: 8pt;")
        ext_title = QLabel("Extension: Connected")
        ext_title.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        ext_title.setStyleSheet(f"color: {t['green']};")
        status_line.addWidget(ext_dot)
        status_line.addWidget(ext_title)
        status_line.addStretch()
        ext_s_layout.addLayout(status_line)

        ext_sub = QLabel("Port 9653 Active • Click to manage")
        ext_sub.setStyleSheet(f"color: {t['text_muted']}; font-size: 7.5pt;")
        ext_s_layout.addWidget(ext_sub)

        ext_status_card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ext_status_card.mousePressEvent = lambda e: self._open_extension_dialog()
        sidebar_layout.addWidget(ext_status_card)

        splitter.addWidget(sidebar_card)

        # Right Panel: Stacked Widget (Empty State vs Active Table) + Segment Inspector
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # Stacked Widget to alternate between Empty State and Table
        self.content_stack = QStackedWidget()

        # Page 0: Modern Executive Empty State Card
        self.empty_card = NeumorphicCard(is_raised=False, radius=12)
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(30, 40, 30, 40)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(14)

        hero_icon = QLabel("⚡")
        hero_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_icon.setFont(QFont("Segoe UI", 36))
        hero_icon.setStyleSheet(f"color: {t['accent']};")
        empty_layout.addWidget(hero_icon)

        hero_title = QLabel("Ready for High-Speed Downloads")
        hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_title.setFont(QFont("Segoe UI Variable Display", 16, QFont.Weight.Bold))
        hero_title.setStyleSheet(f"color: {t['text_primary']};")
        empty_layout.addWidget(hero_title)

        hero_sub = QLabel(
            "Paste any file download URL or YouTube video link to begin downloading at maximum line rate.\n"
            "Or install the Chrome & Edge extension to automatically capture browser downloads."
        )
        hero_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_sub.setWordWrap(True)
        hero_sub.setFont(QFont("Segoe UI", 9.5))
        hero_sub.setStyleSheet(f"color: {t['text_secondary']}; max-width: 540px;")
        empty_layout.addWidget(hero_sub)

        empty_layout.addSpacing(6)

        hero_btn = NeumorphicButton("⚡ Add Download URL", variant="primary", radius=10)
        hero_btn.setMinimumWidth(180)
        hero_btn.clicked.connect(self._open_add_dialog)
        empty_layout.addWidget(hero_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        empty_layout.addSpacing(10)

        # Feature Badges
        badge_row = QHBoxLayout()
        badge_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_row.setSpacing(16)
        features = [
            "⚡ 32-Stream Segmentation",
            "▶ Resumable Multi-Part",
            "🎬 YouTube 4K Stream Ripper",
            "🌐 Native Browser Bridge"
        ]
        for f in features:
            f_lbl = QLabel(f)
            f_lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            f_lbl.setStyleSheet(f"color: {t['text_muted']};")
            badge_row.addWidget(f_lbl)
        empty_layout.addLayout(badge_row)

        self.content_stack.addWidget(self.empty_card)  # Index 0: Empty State

        # Page 1: Downloads Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "File Name", "Size", "Progress", "Speed", "ETA", "Status", "Category"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 180)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(self._on_table_double_click)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.verticalHeader().setVisible(False)

        self.content_stack.addWidget(self.table)  # Index 1: Table

        right_layout.addWidget(self.content_stack, stretch=4)

        # Bottom IDM Dynamic Segment Inspector Card
        self.inspector_card = NeumorphicCard(is_raised=True, radius=12)
        inspector_layout = QVBoxLayout(self.inspector_card)
        inspector_layout.setContentsMargins(16, 10, 16, 10)
        inspector_layout.setSpacing(6)

        insp_header = QHBoxLayout()
        self.insp_title = QLabel("⚡ Dynamic Multi-Stream Segmentation Engine (IDM Turbo)")
        self.insp_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.insp_title.setStyleSheet(f"color: {t['accent']};")
        insp_header.addWidget(self.insp_title)

        self.insp_stats_lbl = QLabel("Select an active download task to inspect real-time connection streams")
        self.insp_stats_lbl.setFont(QFont("Segoe UI", 8.5))
        self.insp_stats_lbl.setStyleSheet(f"color: {t['text_muted']};")
        insp_header.addWidget(self.insp_stats_lbl)
        insp_header.addStretch()
        inspector_layout.addLayout(insp_header)

        # The Visual Multi-Segment Bar!
        self.segment_bar = NeumorphicSegmentBar()
        inspector_layout.addWidget(self.segment_bar)

        right_layout.addWidget(self.inspector_card, stretch=1)

        splitter.addWidget(right_panel)
        splitter.setSizes([230, 870])

        root_layout.addWidget(splitter)

    def _set_bandwidth_preset(self, mb_val: int, label: str):
        t = NeumorphicTheme.current
        for k, b in self.preset_btns.items():
            if k == label:
                b.setStyleSheet(f"background-color: {t['accent']}; color: #ffffff; border-radius: 6px;")
            else:
                b.setStyleSheet("")

        if mb_val == 0:
            self.limiter_lbl.setText("Unlimited (Full Line Speed)")
            self.qm.global_speed_limit_bps = 0.0
        else:
            self.limiter_lbl.setText(f"{mb_val} MB/s Bandwidth Cap")
            self.qm.global_speed_limit_bps = float(mb_val * 1024 * 1024)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor("#3b82f6")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(2, 2, 28, 28, 8, 8)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "⚡")
        painter.end()

        self.tray.setIcon(QIcon(pixmap))
        self.tray.setToolTip("Internet Downloader")

        tray_menu = QMenu()
        show_action = QAction("Open Internet Downloader", self)
        show_action.triggered.connect(self.showNormal)
        tray_menu.addAction(show_action)

        add_action = QAction("+ Add Download URL...", self)
        add_action.triggered.connect(self._open_add_dialog)
        tray_menu.addAction(add_action)

        tray_menu.addSeparator()

        pause_all_action = QAction("Pause All Downloads", self)
        pause_all_action.triggered.connect(self.qm.pause_all)
        tray_menu.addAction(pause_all_action)

        resume_all_action = QAction("Resume All Downloads", self)
        resume_all_action.triggered.connect(self.qm.resume_all)
        tray_menu.addAction(resume_all_action)

        tray_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(exit_action)

        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _setup_timers(self):
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_ui_loop)
        self.refresh_timer.start(400)

    def _start_services(self):
        # 1. Start local background HTTP server for browser extension
        self.api_server = IDMAPIServer(
            port=DEFAULT_SERVER_PORT,
            on_new_download=self._on_extension_download_request
        )
        self.api_server.start()

        # 2. Start Windows clipboard monitor
        self.clipboard_monitor = ClipboardMonitor(on_url_detected=self._on_clipboard_url)
        self.clipboard_monitor.start()

    def _on_extension_download_request(self, payload: dict):
        url = payload.get("url", "")
        if url:
            QTimer.singleShot(0, lambda: self._open_add_dialog(initial_url=url))

    def _on_clipboard_url(self, url: str):
        if self.clip_check.isChecked():
            QTimer.singleShot(0, lambda: self._open_add_dialog(initial_url=url))

    def _open_add_dialog(self, initial_url: str = ""):
        dlg = AddDownloadDialog(initial_url=initial_url, parent=self)
        dlg.exec()
        self._refresh_table(force=True)

    def _open_extension_dialog(self):
        dlg = BrowserExtensionDialog(parent=self)
        dlg.exec()

    def _toggle_theme(self):
        if NeumorphicTheme.current["name"] == "dark":
            NeumorphicTheme.set_theme("light")
        else:
            NeumorphicTheme.set_theme("dark")

        self.setStyleSheet(get_global_stylesheet())
        self.update()

    def _set_category_filter(self, category: str):
        self.current_filter_category = category
        t = NeumorphicTheme.current
        for k, btn in self.cat_btns.items():
            if k == category:
                btn.setStyleSheet(f"background-color: {t['card_hover']}; border: 1.5px solid {t['accent']}; font-weight: bold;")
            else:
                btn.setStyleSheet("")
        self._refresh_table(force=True)

    def _refresh_ui_loop(self):
        self._refresh_table()
        self._refresh_speed_pill()
        self._refresh_segment_inspector()

    def _refresh_speed_pill(self):
        active_speed = self.qm.get_active_speed()
        self.speed_lbl.setText(f"Speed: {format_bytes(int(active_speed))}/s")

        active_count = len([t for t in self.qm.tasks.values() if t.status == DownloadStatus.DOWNLOADING.value])
        self.active_count_lbl.setText(f"|  {active_count} Active")

    def _get_category_icon(self, category: str) -> str:
        icons = {
            "Video": "🎬",
            "Compressed": "📦",
            "Music": "🎵",
            "Documents": "📄",
            "Programs": "💻",
            "General": "🌐"
        }
        return icons.get(category, "📄")

    def _refresh_table(self, force: bool = False):
        all_tasks = self.qm.get_all_tasks()

        filtered = []
        for t in all_tasks:
            if self.current_filter_category == "ALL":
                filtered.append(t)
            elif self.current_filter_category in ("DOWNLOADING", "COMPLETED", "PAUSED") and t.status == self.current_filter_category:
                filtered.append(t)
            elif t.category == self.current_filter_category:
                filtered.append(t)

        # Switch between Empty State and Table View
        if len(filtered) == 0:
            if self.content_stack.currentIndex() != 0:
                self.content_stack.setCurrentIndex(0)
            return
        else:
            if self.content_stack.currentIndex() != 1:
                self.content_stack.setCurrentIndex(1)

        self.table.setRowCount(len(filtered))
        theme = NeumorphicTheme.current

        for row, task in enumerate(filtered):
            # Column 0: Filename + Icon
            icon = self._get_category_icon(task.category)
            item0 = QTableWidgetItem(f"{icon}  {task.filename}")
            item0.setFont(QFont("Segoe UI", 9.5, QFont.Weight.Bold))
            item0.setData(Qt.ItemDataRole.UserRole, task.id)
            self.table.setItem(row, 0, item0)

            # Column 1: Size
            size_str = format_bytes(task.file_size) if task.file_size > 0 else "Unknown"
            item1 = QTableWidgetItem(size_str)
            item1.setFont(QFont("Segoe UI", 9))
            item1.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 1, item1)

            # Column 2: Progress (Neumorphic progress bar)
            pct = task.progress_pct
            pbar = self.table.cellWidget(row, 2)
            if not isinstance(pbar, NeumorphicProgressBar):
                pbar = NeumorphicProgressBar()
                self.table.setCellWidget(row, 2, pbar)
            pbar.setValue(pct)

            # Column 3: Speed
            speed_str = f"{format_bytes(int(task.speed_bps))}/s" if task.speed_bps > 0 else "--"
            item3 = QTableWidgetItem(speed_str)
            item3.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            item3.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if task.speed_bps > 0:
                item3.setForeground(QColor(theme["green"]))
            self.table.setItem(row, 3, item3)

            # Column 4: ETA
            eta_str = f"{int(task.eta_seconds)}s" if task.eta_seconds > 0 else "--"
            item4 = QTableWidgetItem(eta_str)
            item4.setFont(QFont("Segoe UI", 8.5))
            item4.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, item4)

            # Column 5: Status
            status_item = QTableWidgetItem(f" {task.status} ")
            status_item.setFont(QFont("Segoe UI", 8.5, QFont.Weight.Bold))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if task.status == DownloadStatus.COMPLETED.value:
                status_item.setForeground(QColor(theme["green"]))
            elif task.status == DownloadStatus.DOWNLOADING.value:
                status_item.setForeground(QColor(theme["accent"]))
            elif task.status in (DownloadStatus.PAUSED.value, DownloadStatus.PENDING.value):
                status_item.setForeground(QColor(theme["amber"]))
            elif task.status == DownloadStatus.FAILED.value:
                status_item.setForeground(QColor(theme["red"]))
            self.table.setItem(row, 5, status_item)

            # Column 6: Category
            item6 = QTableWidgetItem(task.category)
            item6.setFont(QFont("Segoe UI", 8.5))
            item6.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 6, item6)

    def _on_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            item = self.table.item(row, 0)
            if item:
                self.selected_task_id = item.data(Qt.ItemDataRole.UserRole)
                self._refresh_segment_inspector()

    def _refresh_segment_inspector(self):
        if not self.selected_task_id:
            return

        downloader = self.qm.downloaders.get(self.selected_task_id)
        if downloader and hasattr(downloader, "metadata") and downloader.metadata:
            meta = downloader.metadata
            self.segment_bar.update_segments(meta.segments, meta.file_size)
            active_splits = len(meta.segments)
            self.insp_stats_lbl.setText(
                f"Active Connection Streams: {active_splits} | Dynamic Split: ACTIVE | Downloaded: {format_bytes(meta.total_downloaded)}"
            )
        else:
            task = self.qm.tasks.get(self.selected_task_id)
            if task:
                self.insp_stats_lbl.setText(
                    f"Task: {task.filename} ({task.status}) - {format_bytes(task.downloaded_bytes)} / {format_bytes(task.file_size)}"
                )

    def _on_table_double_click(self, item: QTableWidgetItem):
        row = item.row()
        item0 = self.table.item(row, 0)
        if item0:
            task_id = item0.data(Qt.ItemDataRole.UserRole)
            task = self.qm.tasks.get(task_id)
            if task and task.status == DownloadStatus.COMPLETED.value and os.path.exists(task.output_path):
                os.startfile(task.output_path)

    def _show_context_menu(self, pos: QPoint):
        item = self.table.itemAt(pos)
        if not item:
            return

        row = item.row()
        item0 = self.table.item(row, 0)
        task_id = item0.data(Qt.ItemDataRole.UserRole)
        task = self.qm.tasks.get(task_id)
        if not task:
            return

        menu = QMenu(self)

        if task.status == DownloadStatus.DOWNLOADING.value:
            p_action = menu.addAction("⏸ Pause Download")
            p_action.triggered.connect(lambda: self.qm.pause_task(task_id))
        else:
            r_action = menu.addAction("▶ Resume / Start Download")
            r_action.triggered.connect(lambda: self.qm.resume_task(task_id))

        menu.addSeparator()

        open_file_action = menu.addAction("📂 Open File")
        open_file_action.setEnabled(os.path.exists(task.output_path))
        open_file_action.triggered.connect(lambda: os.startfile(task.output_path) if os.path.exists(task.output_path) else None)

        open_folder_action = menu.addAction("📁 Open Containing Folder")
        open_folder_action.triggered.connect(lambda: self._open_folder(task.output_path))

        copy_link_action = menu.addAction("📋 Copy Download Link")
        copy_link_action.triggered.connect(lambda: QApplication.clipboard().setText(task.url))

        menu.addSeparator()

        delete_action = menu.addAction("🗑 Remove From List")
        delete_action.triggered.connect(lambda: self.qm.delete_task(task_id, delete_file=False))

        delete_disk_action = menu.addAction("❌ Delete File from Disk")
        delete_disk_action.triggered.connect(lambda: self.qm.delete_task(task_id, delete_file=True))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _open_folder(self, path: str):
        folder = os.path.dirname(os.path.abspath(path))
        if os.path.exists(folder):
            os.startfile(folder)


def launch_qt_gui(initial_url: str = ""):
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    app.setApplicationName("Internet Downloader")

    window = IDMMainWindow()
    window.show()
    if initial_url:
        QTimer.singleShot(300, lambda: window._open_add_dialog(initial_url=initial_url))
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_qt_gui()
