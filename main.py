"""
Unified Entry Point for Internet Downloader Executable.
- If launched with CLI arguments: runs headless CLI with Rich progress bars.
- If launched without arguments (e.g. double-clicked): launches Internet Downloader Modern GUI.
"""

import sys

def hide_console():
    """Hides console window on Windows when launching GUI mode."""
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE = 0
        except Exception:
            pass


def run():
    # If launched with arguments
    if len(sys.argv) > 1:
        arg1 = sys.argv[1]
        if arg1.startswith("idm://"):
            hide_console()
            raw_url = arg1[6:]
            from segmented_downloader.gui_qt import launch_qt_gui
            launch_qt_gui(initial_url=raw_url)
        elif "--gui" in sys.argv:
            hide_console()
            initial_url = ""
            for a in sys.argv[1:]:
                if a != "--gui" and (a.startswith("http://") or a.startswith("https://") or a.startswith("ftp://")):
                    initial_url = a
                    break
            from segmented_downloader.gui_qt import launch_qt_gui
            launch_qt_gui(initial_url=initial_url)
        elif "--add-url" in sys.argv:
            hide_console()
            idx = sys.argv.index("--add-url")
            url = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else ""
            from segmented_downloader.gui_qt import launch_qt_gui
            launch_qt_gui(initial_url=url)
        else:
            from segmented_downloader.cli import main as cli_main
            cli_main()
    else:
        # Double-clicked from Windows File Explorer without arguments
        hide_console()
        try:
            from segmented_downloader.gui_qt import launch_qt_gui
            launch_qt_gui()
        except Exception:
            try:
                from segmented_downloader.gui import launch_gui
                launch_gui()
            except Exception:
                from segmented_downloader.cli import main as cli_main
                cli_main()

if __name__ == "__main__":
    run()
