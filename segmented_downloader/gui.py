"""
IDM-Style Graphical User Interface for Segmented Downloader.
Built with Tkinter for minimal footprint and maximum portability in standalone executables.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import threading
import time
import subprocess

from .downloader import SegmentedDownloader, DownloadConfig
from .model import DownloadStatus, SegmentStatus


def format_bytes(n: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:3.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


class IDMDownloaderGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Internet Downloader - Segmented Download Manager")
        self.root.geometry("820x620")
        self.root.minsize(720, 520)

        # Style configuration
        self.style = ttk.Style()
        self.style.theme_use("clam")
        
        # Color palette
        self.bg_color = "#1e1e2e"
        self.card_bg = "#252538"
        self.fg_color = "#cdd6f4"
        self.accent_color = "#89b4fa"
        self.green_color = "#a6e3a1"
        self.yellow_color = "#f9e2af"
        self.red_color = "#f38ba8"

        self.root.configure(bg=self.bg_color)

        self.downloader: SegmentedDownloader = None
        self._is_updating = False

        self._build_ui()

    def _build_ui(self):
        # Header / Title Banner
        header_frame = tk.Frame(self.root, bg="#181825", pady=10, padx=16)
        header_frame.pack(fill=tk.X)

        title_lbl = tk.Label(
            header_frame,
            text="⚡ IDM Portable Downloader",
            font=("Segoe UI", 16, "bold"),
            bg="#181825",
            fg=self.accent_color
        )
        title_lbl.pack(side=tk.LEFT)

        sub_lbl = tk.Label(
            header_frame,
            text="Multi-Threaded Dynamic Segmentation Engine",
            font=("Segoe UI", 9),
            bg="#181825",
            fg="#a6adc8"
        )
        sub_lbl.pack(side=tk.LEFT, padx=12, pady=4)

        # Main Container
        main_container = tk.Frame(self.root, bg=self.bg_color, padx=16, pady=12)
        main_container.pack(fill=tk.BOTH, expand=True)

        # URL Input Section
        input_frame = tk.LabelFrame(
            main_container,
            text=" Download Configuration ",
            font=("Segoe UI", 10, "bold"),
            bg=self.card_bg,
            fg=self.accent_color,
            padx=12,
            pady=10
        )
        input_frame.pack(fill=tk.X, pady=(0, 10))

        # Row 1: URL input
        url_lbl = tk.Label(input_frame, text="URL:", bg=self.card_bg, fg=self.fg_color, font=("Segoe UI", 9))
        url_lbl.grid(row=0, column=0, sticky="w", pady=4)

        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(
            input_frame,
            textvariable=self.url_var,
            font=("Consolas", 10),
            bg="#313244",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.FLAT
        )
        self.url_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=(8, 8), pady=4)

        # Row 2: Destination path
        out_lbl = tk.Label(input_frame, text="Save To:", bg=self.card_bg, fg=self.fg_color, font=("Segoe UI", 9))
        out_lbl.grid(row=1, column=0, sticky="w", pady=4)

        self.out_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self.out_entry = tk.Entry(
            input_frame,
            textvariable=self.out_var,
            font=("Segoe UI", 9),
            bg="#313244",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.FLAT
        )
        self.out_entry.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(8, 8), pady=4)

        browse_btn = tk.Button(
            input_frame,
            text="Browse...",
            command=self._on_browse,
            bg="#45475a",
            fg="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            cursor="hand2"
        )
        browse_btn.grid(row=1, column=4, sticky="ew", pady=4)

        # Row 3: Connections and Speed Limit
        conn_lbl = tk.Label(input_frame, text="Connections:", bg=self.card_bg, fg=self.fg_color, font=("Segoe UI", 9))
        conn_lbl.grid(row=2, column=0, sticky="w", pady=4)

        self.conn_var = tk.StringVar(value="8")
        conn_combo = ttk.Combobox(
            input_frame,
            textvariable=self.conn_var,
            values=["1", "2", "4", "8", "16", "32"],
            state="readonly",
            width=8
        )
        conn_combo.grid(row=2, column=1, sticky="w", padx=(8, 16), pady=4)

        limit_lbl = tk.Label(input_frame, text="Speed Limit (KB/s):", bg=self.card_bg, fg=self.fg_color, font=("Segoe UI", 9))
        limit_lbl.grid(row=2, column=2, sticky="w", pady=4)

        self.limit_var = tk.StringVar(value="0")
        limit_entry = tk.Entry(
            input_frame,
            textvariable=self.limit_var,
            font=("Segoe UI", 9),
            width=10,
            bg="#313244",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.FLAT
        )
        limit_entry.grid(row=2, column=3, sticky="w", padx=(8, 8), pady=4)

        self.start_btn = tk.Button(
            input_frame,
            text="▶ Start Download",
            command=self._start_download,
            bg="#89b4fa",
            fg="#11111b",
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2"
        )
        self.start_btn.grid(row=2, column=4, sticky="ew", pady=4)

        input_frame.columnconfigure(1, weight=1)

        # Overall Status Card
        status_frame = tk.LabelFrame(
            main_container,
            text=" Transfer Overview ",
            font=("Segoe UI", 10, "bold"),
            bg=self.card_bg,
            fg=self.accent_color,
            padx=12,
            pady=8
        )
        status_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress_bar = ttk.Progressbar(status_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(4, 8))

        stats_row = tk.Frame(status_frame, bg=self.card_bg)
        stats_row.pack(fill=tk.X)

        self.status_lbl = tk.Label(stats_row, text="Status: Ready", bg=self.card_bg, fg="#a6adc8", font=("Segoe UI", 9, "bold"))
        self.status_lbl.pack(side=tk.LEFT)

        self.speed_lbl = tk.Label(stats_row, text="Speed: --", bg=self.card_bg, fg=self.green_color, font=("Segoe UI", 9, "bold"))
        self.speed_lbl.pack(side=tk.LEFT, padx=16)

        self.size_lbl = tk.Label(stats_row, text="Downloaded: 0 B / 0 B", bg=self.card_bg, fg=self.fg_color, font=("Segoe UI", 9))
        self.size_lbl.pack(side=tk.LEFT, padx=16)

        self.eta_lbl = tk.Label(stats_row, text="ETA: --", bg=self.card_bg, fg=self.yellow_color, font=("Segoe UI", 9))
        self.eta_lbl.pack(side=tk.RIGHT)

        # Control Buttons
        btn_frame = tk.Frame(status_frame, bg=self.card_bg)
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        self.pause_btn = tk.Button(
            btn_frame, text="⏸ Pause", command=self._pause_download, state=tk.DISABLED,
            bg="#45475a", fg="#ffffff", relief=tk.FLAT, font=("Segoe UI", 9), cursor="hand2"
        )
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.resume_btn = tk.Button(
            btn_frame, text="▶ Resume", command=self._resume_download, state=tk.DISABLED,
            bg="#45475a", fg="#ffffff", relief=tk.FLAT, font=("Segoe UI", 9), cursor="hand2"
        )
        self.resume_btn.pack(side=tk.LEFT, padx=6)

        self.cancel_btn = tk.Button(
            btn_frame, text="✖ Cancel", command=self._cancel_download, state=tk.DISABLED,
            bg="#f38ba8", fg="#11111b", relief=tk.FLAT, font=("Segoe UI", 9), cursor="hand2"
        )
        self.cancel_btn.pack(side=tk.LEFT, padx=6)

        self.open_file_btn = tk.Button(
            btn_frame, text="📂 Open File", command=self._open_file, state=tk.DISABLED,
            bg="#a6e3a1", fg="#11111b", relief=tk.FLAT, font=("Segoe UI", 9), cursor="hand2"
        )
        self.open_file_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.open_folder_btn = tk.Button(
            btn_frame, text="📁 Open Folder", command=self._open_folder, state=tk.DISABLED,
            bg="#89dceb", fg="#11111b", relief=tk.FLAT, font=("Segoe UI", 9), cursor="hand2"
        )
        self.open_folder_btn.pack(side=tk.RIGHT, padx=6)

        # Segment Details Table (IDM CFragmentsList View)
        segments_frame = tk.LabelFrame(
            main_container,
            text=" Active Connection Segments (Dynamic Splitting) ",
            font=("Segoe UI", 10, "bold"),
            bg=self.card_bg,
            fg=self.accent_color,
            padx=8,
            pady=8
        )
        segments_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("conn", "range", "downloaded", "remaining", "pct", "status")
        self.tree = ttk.Treeview(segments_frame, columns=columns, show="headings", height=8)

        self.tree.heading("conn", text="Conn #")
        self.tree.heading("range", text="Byte Range")
        self.tree.heading("downloaded", text="Downloaded")
        self.tree.heading("remaining", text="Remaining")
        self.tree.heading("pct", text="Progress")
        self.tree.heading("status", text="Status")

        self.tree.column("conn", width=70, anchor="center")
        self.tree.column("range", width=220, anchor="w")
        self.tree.column("downloaded", width=110, anchor="e")
        self.tree.column("remaining", width=110, anchor="e")
        self.tree.column("pct", width=90, anchor="center")
        self.tree.column("status", width=110, anchor="center")

        tree_scroll = ttk.Scrollbar(segments_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_browse(self):
        dest = filedialog.askdirectory(initialdir=self.out_var.get())
        if dest:
            self.out_var.set(dest)

    def _start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please provide a valid URL to download.")
            return

        try:
            conns = int(self.conn_var.get())
        except ValueError:
            conns = 8

        try:
            speed_limit_kb = float(self.limit_var.get())
        except ValueError:
            speed_limit_kb = 0.0

        dest_dir = self.out_var.get().strip()
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)

        config = DownloadConfig(
            connections=conns,
            max_speed_bps=speed_limit_kb * 1024.0,
            dynamic_split=True
        )

        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.NORMAL)
        self.resume_btn.config(state=tk.DISABLED)
        self.open_file_btn.config(state=tk.DISABLED)
        self.open_folder_btn.config(state=tk.DISABLED)
        self.status_lbl.config(text="Status: Probing server...", fg=self.accent_color)

        def runner():
            try:
                dest_dir = self.out_var.get().strip() or os.path.join(os.path.expanduser("~"), "Downloads")
                os.makedirs(dest_dir, exist_ok=True)
                self.downloader = SegmentedDownloader(url=url, output_path=dest_dir, config=config)
                self.downloader.start(wait=False)
                self._is_updating = True
                self.root.after(100, self._update_loop)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Download Error", str(e)))
                self.root.after(0, self._reset_controls)

        threading.Thread(target=runner, daemon=True).start()

    def _update_loop(self):
        if not self.downloader or not self._is_updating:
            return

        meta = self.downloader.metadata
        if meta:
            pct = meta.progress_pct
            self.progress_bar["value"] = pct

            speed_str = format_bytes(int(self.downloader.current_speed_bps)) + "/s"
            self.speed_lbl.config(text=f"Speed: {speed_str}")

            downloaded_str = format_bytes(meta.total_downloaded)
            total_str = format_bytes(meta.file_size) if meta.file_size > 0 else "Unknown"
            self.size_lbl.config(text=f"Downloaded: {downloaded_str} / {total_str} ({pct:.1f}%)")

            eta_str = f"{int(self.downloader.eta_seconds)}s" if self.downloader.eta_seconds > 0 else "--"
            self.eta_lbl.config(text=f"ETA: {eta_str}")

            status_str = f"Status: {meta.status.value}"
            status_fg = self.green_color if meta.status == DownloadStatus.COMPLETED else \
                        self.yellow_color if meta.status == DownloadStatus.PAUSED else \
                        self.accent_color
            self.status_lbl.config(text=status_str, fg=status_fg)

            # Update segments tree
            # Clear existing items
            for item in self.tree.get_children():
                self.tree.delete(item)

            for s in meta.segments:
                range_str = f"{s.start_byte:,} - {s.end_byte:,}"
                self.tree.insert(
                    "",
                    "end",
                    values=(
                        f"#{s.id + 1}",
                        range_str,
                        format_bytes(s.downloaded_bytes),
                        format_bytes(s.remaining_bytes),
                        f"{s.progress_pct:.1f}%",
                        s.status.value
                    )
                )

            if meta.status == DownloadStatus.COMPLETED:
                self._is_updating = False
                self.pause_btn.config(state=tk.DISABLED)
                self.resume_btn.config(state=tk.DISABLED)
                self.cancel_btn.config(state=tk.DISABLED)
                self.start_btn.config(state=tk.NORMAL)
                self.open_file_btn.config(state=tk.NORMAL)
                self.open_folder_btn.config(state=tk.NORMAL)
                self.status_lbl.config(text="Status: Download Complete! ✔", fg=self.green_color)
                return

            if meta.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                self._is_updating = False
                self._reset_controls()
                return

        self.root.after(250, self._update_loop)

    def _pause_download(self):
        if self.downloader:
            self.downloader.pause()
            self.pause_btn.config(state=tk.DISABLED)
            self.resume_btn.config(state=tk.NORMAL)
            self.status_lbl.config(text="Status: Paused ⏸", fg=self.yellow_color)

    def _resume_download(self):
        if self.downloader:
            self.resume_btn.config(state=tk.DISABLED)
            self.pause_btn.config(state=tk.NORMAL)
            self.status_lbl.config(text="Status: Resuming...", fg=self.accent_color)
            self._is_updating = True
            threading.Thread(target=lambda: self.downloader.start(wait=False), daemon=True).start()
            self.root.after(100, self._update_loop)

    def _cancel_download(self):
        if self.downloader:
            if messagebox.askyesno("Cancel Download", "Are you sure you want to cancel and remove incomplete files?"):
                self.downloader.cancel(remove_files=True)
                self._is_updating = False
                self._reset_controls()
                self.status_lbl.config(text="Status: Cancelled", fg=self.red_color)

    def _open_file(self):
        if self.downloader and self.downloader.output_path and os.path.exists(self.downloader.output_path):
            os.startfile(self.downloader.output_path)

    def _open_folder(self):
        if self.downloader and self.downloader.output_path:
            folder = os.path.dirname(os.path.abspath(self.downloader.output_path))
            if os.path.exists(folder):
                os.startfile(folder)

    def _reset_controls(self):
        self.start_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED)
        self.resume_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.DISABLED)


def launch_gui(initial_url: str = ""):
    try:
        from .gui_qt import launch_qt_gui
        launch_qt_gui(initial_url=initial_url)
    except Exception as e:
        # Fallback to Tkinter GUI
        root = tk.Tk()
        app = IDMDownloaderGUI(root)
        if initial_url:
            app.url_var.set(initial_url)
        root.mainloop()


if __name__ == "__main__":
    launch_gui()
