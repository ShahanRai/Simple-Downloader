"""
Simple Downloader Windows Setup Wizard.
Provides a modern Obsidian Fluent setup experience for:
- Fresh Installation to any drive (C:, D:, etc.)
- Repair / Update existing installation
- Complete Uninstallation with clean registry and shortcut cleanup
"""

import sys
import os
import shutil
import json
import time
import winreg
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QRadioButton, QButtonGroup,
    QFileDialog, QProgressBar, QMessageBox, QFrame
)
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal, QThread

try:
    import win32com.client
    HAS_WIN32COM = True
except ImportError:
    HAS_WIN32COM = False

try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SimpleDownloader.Setup.1.0")
except Exception:
    pass


def terminate_process_by_name(exe_name: str):
    """Terminates processes matching exe_name natively without relying on taskkill."""
    try:
        import ctypes
        from ctypes import wintypes
        TH32CS_SNAPPROCESS = 0x00000002
        PROCESS_TERMINATE = 0x0001

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('cntUsage', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_void_p),
                ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD),
                ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', wintypes.LONG),
                ('dwFlags', wintypes.DWORD),
                ('szExeFile', ctypes.c_char * 260)
            ]

        k32 = ctypes.windll.kernel32
        h_snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h_snap == -1:
            return
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        target = exe_name.lower().encode('utf-8')
        if k32.Process32First(h_snap, ctypes.byref(pe)):
            while True:
                if pe.szExeFile.lower() == target:
                    hp = k32.OpenProcess(PROCESS_TERMINATE, False, pe.th32ProcessID)
                    if hp:
                        k32.TerminateProcess(hp, 0)
                        k32.CloseHandle(hp)
                if not k32.Process32Next(h_snap, ctypes.byref(pe)):
                    break
        k32.CloseHandle(h_snap)
    except Exception:
        pass

PAGE_MODE = 0
PAGE_DIR = 1
PAGE_OPTS = 2
PAGE_UNINSTALL = 3
PAGE_PROGRESS = 4
PAGE_FINISH = 5


def get_installed_dir() -> Optional[str]:
    reg_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\InternetDownloader"
    for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
        try:
            with winreg.OpenKey(hive, reg_path) as k:
                val, _ = winreg.QueryValueEx(k, "InstallLocation")
                if val and os.path.exists(val):
                    return os.path.normpath(val)
        except Exception:
            pass

    for candidate in [
        r"C:\Program Files\Simple Downloader",
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Simple Downloader"),
        os.path.join(os.getenv("LOCALAPPDATA", "C:\\"), "Programs", "Simple Downloader"),
        r"C:\Program Files (x86)\Simple Downloader",
        r"C:\Simple Downloader",
        r"D:\Simple Downloader"
    ]:
        if os.path.exists(os.path.join(candidate, "InternetDownloader.exe")):
            return os.path.normpath(candidate)
    return None


def get_default_install_dir() -> str:
    prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    return os.path.normpath(os.path.join(prog_files, "Simple Downloader"))


def get_source_root() -> str:
    """Returns root directory containing files to install."""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            if os.path.exists(os.path.join(sys._MEIPASS, "InternetDownloader.exe")):
                return sys._MEIPASS
        exe_dir = os.path.dirname(sys.executable)
        if os.path.exists(os.path.join(exe_dir, "InternetDownloader.exe")):
            return exe_dir
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_app_icon_path() -> Optional[str]:
    candidates = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            candidates.append(os.path.join(sys._MEIPASS, "installer", "icon.ico"))
            candidates.append(os.path.join(sys._MEIPASS, "icon.ico"))
            candidates.append(os.path.join(sys._MEIPASS, "src-tauri", "icons", "icon.ico"))
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "installer", "icon.ico"))
        candidates.append(os.path.join(exe_dir, "icon.ico"))
        candidates.append(sys.executable)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(script_dir, "icon.ico"))
    candidates.append(os.path.join(script_dir, "..", "icon.ico"))
    candidates.append(os.path.join(script_dir, "..", "installer", "icon.ico"))
    candidates.append(os.path.join(script_dir, "..", "src-tauri", "icons", "icon.ico"))

    for c in candidates:
        if c and os.path.exists(c):
            return os.path.normpath(c)
    return None


def get_app_png_path() -> Optional[str]:
    candidates = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            candidates.append(os.path.join(sys._MEIPASS, "ui", "icon.png"))
            candidates.append(os.path.join(sys._MEIPASS, "src-tauri", "icons", "icon.png"))
            candidates.append(os.path.join(sys._MEIPASS, "icon.png"))
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "ui", "icon.png"))
        candidates.append(os.path.join(exe_dir, "icon.png"))
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(script_dir, "..", "ui", "icon.png"))
    candidates.append(os.path.join(script_dir, "..", "src-tauri", "icons", "icon.png"))
    candidates.append(os.path.join(script_dir, "icon.png"))
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.normpath(c)
    return None


def get_asset_path(filename: str) -> str:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        for sub in ["installer", ""]:
            p = os.path.join(sys._MEIPASS, sub, filename)
            if os.path.exists(p):
                return p.replace('\\', '/')
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for sub in ["", "installer", "../installer"]:
        p = os.path.abspath(os.path.join(script_dir, sub, filename))
        if os.path.exists(p):
            return p.replace('\\', '/')
    return filename


SETUP_STYLESHEET = """
QWizard {
    background-color: #0e1015;
    color: #f3f4f6;
    font-family: -apple-system, "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
}
QWizardPage {
    background-color: #0e1015;
    color: #f3f4f6;
}
QLabel {
    color: #f3f4f6;
}
QLineEdit {
    background-color: #12141a;
    border: 1px solid #282d38;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f3f4f6;
    font-size: 9pt;
    selection-background-color: #4f46e5;
}
QLineEdit:focus {
    border: 1px solid #6366f1;
    background-color: #161922;
}
QPushButton {
    background-color: #1f232c;
    border: 1px solid #282d38;
    border-radius: 6px;
    padding: 6px 16px;
    color: #e2e8f0;
    font-size: 9pt;
    font-weight: 500;
    min-height: 18px;
}
QPushButton:hover {
    background-color: #282d38;
    border-color: #4b5563;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #161920;
}
QPushButton:disabled {
    background-color: #12141a;
    border-color: #1f232c;
    color: #4b5563;
}
/* Primary Next & Finish buttons */
QWizard QPushButton[text="&Next >"], QWizard QPushButton[text="Next >"], 
QWizard QPushButton[text="&Finish"], QWizard QPushButton[text="Finish"],
QPushButton#primaryWizardBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #6366f1);
    border: 1px solid #6366f1;
    color: #ffffff;
    font-weight: 600;
    border-radius: 6px;
    padding: 6px 20px;
}
QWizard QPushButton[text="&Next >"]:hover, QWizard QPushButton[text="Next >"]:hover, 
QWizard QPushButton[text="&Finish"]:hover, QWizard QPushButton[text="Finish"]:hover,
QPushButton#primaryWizardBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4338ca, stop:1 #4f46e5);
    border-color: #818cf8;
}
QWizard QPushButton[text="&Next >"]:disabled, QWizard QPushButton[text="Next >"]:disabled, 
QWizard QPushButton[text="&Finish"]:disabled, QWizard QPushButton[text="Finish"]:disabled,
QPushButton#primaryWizardBtn:disabled {
    background: #1f232c;
    border: 1px solid #282d38;
    color: #4b5563;
}
QRadioButton {
    color: #f3f4f6;
    font-size: 9.5pt;
    font-weight: 500;
    spacing: 8px;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border-radius: 7px;
    border: 1.5px solid #4b5563;
    background: #12141a;
}
QRadioButton::indicator:checked {
    border-color: #6366f1;
    background: #6366f1;
}
QCheckBox {
    color: #d1d5db;
    font-size: 9pt;
    spacing: 7px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3.5px;
    border: 1.5px solid #384050;
    background: #12141a;
}
QCheckBox::indicator:hover {
    border-color: #6366f1;
}
QCheckBox::indicator:checked {
    border-color: #6366f1;
    background: #6366f1;
    image: url("__CHECK_IMG_PATH__");
}
QProgressBar {
    background-color: #12141a;
    border: 1px solid #282d38;
    border-radius: 5px;
    height: 14px;
    text-align: center;
    color: #ffffff;
    font-size: 8.5pt;
    font-weight: 600;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:0.6 #818cf8, stop:1 #38bdf8);
    border-radius: 4px;
}
"""


def get_styled_sheet() -> str:
    check_img = get_asset_path("check.png")
    return SETUP_STYLESHEET.replace("__CHECK_IMG_PATH__", check_img)



class InstallWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, target_dir: str, options: dict, is_repair: bool = False):
        super().__init__()
        self.target_dir = os.path.normpath(target_dir.strip().replace('/', '\\'))
        self.options = options
        self.is_repair = is_repair

    def run(self):
        try:
            source_dir = get_source_root()
            action_name = "Repairing" if self.is_repair else "Installing"

            self.progress.emit(5, "Closing running instances of Simple Downloader...")
            terminate_process_by_name("InternetDownloader.exe")
            terminate_process_by_name("IDMPortable.exe")
            time.sleep(0.3)

            self.progress.emit(10, f"Creating destination directory: {self.target_dir}...")
            try:
                os.makedirs(self.target_dir, exist_ok=True)
            except Exception as e:
                raise PermissionError(f"Failed to create target directory '{self.target_dir}': {e}")

            # Copy current setup executable as uninstall.exe for permanent Windows uninstaller registration
            if getattr(sys, 'frozen', False):
                try:
                    shutil.copy2(sys.executable, os.path.join(self.target_dir, "uninstall.exe"))
                except Exception:
                    pass

            self.progress.emit(15, f"{action_name} core application files...")

            items_to_copy = [
                "InternetDownloader.exe",
                "WebView2Loader.dll",
                "segmented_downloader",
                "browser_extension",
                "installer",
                "icon.ico",
                "main.py",
                "README.md",
                "IDMGCExt.crx",
                "browser_extension.zip"
            ]

            total_items = len(items_to_copy)
            copied_count = 0
            for idx, item in enumerate(items_to_copy):
                src = os.path.join(source_dir, item)
                dst = os.path.join(self.target_dir, item)
                if os.path.exists(src):
                    for attempt in range(4):
                        try:
                            if os.path.isdir(src):
                                shutil.copytree(src, dst, dirs_exist_ok=True)
                            else:
                                shutil.copy2(src, dst)
                            copied_count += 1
                            break
                        except PermissionError:
                            if attempt == 3:
                                raise
                            time.sleep(0.4)

                pct = int(15 + ((idx + 1) / max(1, total_items)) * 45)
                self.progress.emit(pct, f"Writing {item}...")

            if copied_count == 0:
                raise RuntimeError(f"Could not locate installation source files in '{source_dir}'")

            # After items_to_copy loop, verify WebView2Loader.dll
            webview_dll = os.path.join(self.target_dir, "WebView2Loader.dll")
            if not os.path.exists(webview_dll):
                script_dir = os.path.dirname(os.path.abspath(__file__))
                alt_paths = [
                    os.path.join(script_dir, "..", "src-tauri", "target", "release", "WebView2Loader.dll"),
                    os.path.join(source_dir, "..", "src-tauri", "target", "release", "WebView2Loader.dll"),
                    os.path.join(os.path.dirname(sys.executable), "WebView2Loader.dll"),
                ]
                for alt in alt_paths:
                    if os.path.exists(alt):
                        try:
                            shutil.copy2(alt, webview_dll)
                            break
                        except Exception:
                            pass

            self.progress.emit(65, "Configuring Browser Integration & Native Messaging hosts...")
            if self.options.get("register_extension", True):
                self._install_browser_extensions()

            self.progress.emit(80, "Registering Windows idm:// URL Protocol Handler...")
            if self.options.get("url_protocol", True):
                self._register_protocol_handler()

            self.progress.emit(88, "Creating Windows shortcuts...")
            # Clean up any legacy or broken shortcuts pointing to non-existent executables or IDMPortable
            if HAS_WIN32COM:
                try:
                    shell = win32com.client.Dispatch("WScript.Shell")
                    cleanup_dirs = []
                    for sf in ["Desktop", "AllUsersDesktop", "Programs", "AllUsersPrograms"]:
                        try:
                            f = shell.SpecialFolders(sf)
                            if f and os.path.exists(f):
                                cleanup_dirs.append(f)
                        except Exception:
                            pass
                    user_prof = os.environ.get("USERPROFILE")
                    if user_prof:
                        for sub in ["Desktop", os.path.join("OneDrive", "Desktop")]:
                            d = os.path.join(user_prof, sub)
                            if os.path.exists(d) and d not in cleanup_dirs:
                                cleanup_dirs.append(d)
                    pub = os.environ.get("PUBLIC", r"C:\Users\Public")
                    if pub:
                        d = os.path.join(pub, "Desktop")
                        if os.path.exists(d) and d not in cleanup_dirs:
                            cleanup_dirs.append(d)

                    for folder in cleanup_dirs:
                        for name in ["Simple Downloader.lnk", "Internet Downloader.lnk", "IDMPortable.lnk", "IDM.lnk"]:
                            p = os.path.join(folder, name)
                            if os.path.exists(p):
                                try:
                                    os.remove(p)
                                except Exception:
                                    pass
                except Exception:
                    pass

            if self.options.get("desktop_shortcut", True):
                self._create_shortcut("desktop")
            if self.options.get("start_menu_shortcut", True):
                self._create_shortcut("start_menu")

            self.progress.emit(95, "Registering Windows App Control Entry...")
            self._register_uninstaller()

            self.progress.emit(100, f"{action_name} completed successfully!")
            self.finished.emit(True, "Complete")
        except Exception as e:
            self.finished.emit(False, str(e))

    def _install_browser_extensions(self):
        IDM_CHROME_ID = "ngpampappnmepgilojfohadhhmbhlaek"
        CHROME_UPDATE_URL = "https://clients2.google.com/service/update2/crx"

        for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            for root_key in [
                rf"Software\Google\Chrome\Extensions\{IDM_CHROME_ID}",
                rf"Software\Wow6432Node\Google\Chrome\Extensions\{IDM_CHROME_ID}"
            ]:
                try:
                    with winreg.CreateKey(hive, root_key) as k:
                        winreg.SetValueEx(k, "update_url", 0, winreg.REG_SZ, CHROME_UPDATE_URL)
                except Exception:
                    pass

        for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            for root_key in [
                rf"Software\Microsoft\Edge\Extensions\{IDM_CHROME_ID}",
                rf"Software\Wow6432Node\Microsoft\Edge\Extensions\{IDM_CHROME_ID}"
            ]:
                try:
                    with winreg.CreateKey(hive, root_key) as k:
                        winreg.SetValueEx(k, "update_url", 0, winreg.REG_SZ, CHROME_UPDATE_URL)
                except Exception:
                    pass

        native_dir = os.path.join(self.target_dir, "browser_extension", "native_messaging")
        os.makedirs(native_dir, exist_ok=True)
        bat_path = os.path.join(native_dir, "idm_host.bat")

        hosts = [
            ("com.tonec.idm", "com.tonec.idm.json"),
            ("com.idm.downloader", "com.idm.downloader.json")
        ]

        for host_name, json_name in hosts:
            manifest_path = os.path.join(native_dir, json_name)
            manifest_data = {
                "name": host_name,
                "description": "Internet Downloader Native Messaging Host",
                "path": bat_path,
                "type": "stdio",
                "allowed_origins": [
                    f"chrome-extension://{IDM_CHROME_ID}/",
                    "chrome-extension://*",
                    "edge-extension://*"
                ]
            }
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2)

            for browser in ["Google\\Chrome", "Microsoft\\Edge"]:
                for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
                    try:
                        reg_key = rf"Software\{browser}\NativeMessagingHosts\{host_name}"
                        with winreg.CreateKey(hive, reg_key) as key:
                            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, manifest_path)
                    except Exception:
                        pass

        ff_manifest = os.path.join(native_dir, "com.idm.downloader.firefox.json")
        ff_data = {
            "name": "com.idm.downloader",
            "description": "Internet Downloader Native Messaging Host for Firefox",
            "path": bat_path,
            "type": "stdio",
            "allowed_extensions": ["idm-modern@antigravity.internal"]
        }
        with open(ff_manifest, "w", encoding="utf-8") as f:
            json.dump(ff_data, f, indent=2)

        for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            try:
                with winreg.CreateKey(hive, r"Software\Mozilla\NativeMessagingHosts\com.idm.downloader") as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, ff_manifest)
            except Exception:
                pass

    def _register_protocol_handler(self):
        try:
            exe_target = os.path.join(self.target_dir, "InternetDownloader.exe")
            for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
                try:
                    with winreg.CreateKey(hive, r"Software\Classes\idm") as key:
                        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Internet Downloader Protocol")
                        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

                    with winreg.CreateKey(hive, r"Software\Classes\idm\shell\open\command") as key:
                        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_target}" "%1"')
                except Exception:
                    pass
        except Exception as e:
            print(f"Protocol registration error: {e}")

    def _create_shortcut(self, target_type: str):
        if not HAS_WIN32COM:
            return

        shell = win32com.client.Dispatch("WScript.Shell")
        if target_type == "desktop":
            link_dir = shell.SpecialFolders("Desktop")
        else:
            programs_dir = shell.SpecialFolders("Programs")
            link_dir = os.path.join(programs_dir, "Simple Downloader")
            os.makedirs(link_dir, exist_ok=True)

        shortcut_path = os.path.join(link_dir, "Simple Downloader.lnk")
        try:
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
        except Exception:
            pass

        shortcut = shell.CreateShortCut(shortcut_path)

        exe_target = os.path.join(self.target_dir, "InternetDownloader.exe")
        shortcut.TargetPath = exe_target
        shortcut.WorkingDirectory = self.target_dir
        shortcut.Description = "Simple Downloader - High-Performance Multi-Connection Downloader"
        
        target_ico = os.path.join(self.target_dir, "icon.ico")
        if os.path.exists(target_ico):
            shortcut.IconLocation = f"{target_ico},0"
        elif os.path.exists(exe_target):
            shortcut.IconLocation = f"{exe_target},0"

        shortcut.save()

        # Force Windows Shell to refresh desktop and taskbar icon cache
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        except Exception:
            pass

    def _register_uninstaller(self):
        uninstaller_exe = os.path.join(self.target_dir, "uninstall.exe")
        if not os.path.exists(uninstaller_exe):
            uninstaller_exe = sys.executable if getattr(sys, 'frozen', False) else f'python.exe "{os.path.abspath(__file__)}"'

        exe_target = os.path.join(self.target_dir, "InternetDownloader.exe")
        target_ico = os.path.join(self.target_dir, "icon.ico")
        display_ico = target_ico if os.path.exists(target_ico) else exe_target

        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\InternetDownloader"
        for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            try:
                with winreg.CreateKey(hive, reg_path) as key:
                    winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Simple Downloader")
                    winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.0.0")
                    winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Simple Downloader Team")
                    winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, self.target_dir)
                    winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller_exe}"')
                    winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, display_ico)
            except Exception as e:
                pass


class UninstallWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, target_dir: str, clean_data: bool):
        super().__init__()
        self.target_dir = os.path.normpath(target_dir.strip().replace('/', '\\'))
        self.clean_data = clean_data

    def run(self):
        try:
            self.progress.emit(15, "Terminating running instances of Simple Downloader...")
            terminate_process_by_name("InternetDownloader.exe")
            terminate_process_by_name("IDMPortable.exe")
            time.sleep(0.3)

            self.progress.emit(30, "Removing Desktop & Start Menu shortcuts...")
            if HAS_WIN32COM:
                try:
                    shell = win32com.client.Dispatch("WScript.Shell")
                    cleanup_dirs = []
                    for sf in ["Desktop", "AllUsersDesktop"]:
                        try:
                            f = shell.SpecialFolders(sf)
                            if f and os.path.exists(f):
                                cleanup_dirs.append(f)
                        except Exception:
                            pass
                    user_prof = os.environ.get("USERPROFILE")
                    if user_prof:
                        for sub in ["Desktop", os.path.join("OneDrive", "Desktop")]:
                            d = os.path.join(user_prof, sub)
                            if os.path.exists(d) and d not in cleanup_dirs:
                                cleanup_dirs.append(d)
                    pub = os.environ.get("PUBLIC", r"C:\Users\Public")
                    if pub:
                        d = os.path.join(pub, "Desktop")
                        if os.path.exists(d) and d not in cleanup_dirs:
                            cleanup_dirs.append(d)

                    for folder in cleanup_dirs:
                        for name in ["Simple Downloader.lnk", "Internet Downloader.lnk", "IDMPortable.lnk", "IDM.lnk"]:
                            p = os.path.join(folder, name)
                            if os.path.exists(p):
                                try:
                                    os.remove(p)
                                except Exception:
                                    pass

                    programs_dir = shell.SpecialFolders("Programs")
                    start_folder = os.path.join(programs_dir, "Simple Downloader")
                    if os.path.exists(start_folder):
                        shutil.rmtree(start_folder, ignore_errors=True)
                except Exception:
                    pass

            self.progress.emit(50, "Unregistering Browser Native Messaging hosts...")
            for browser in ["Google\\Chrome", "Microsoft\\Edge"]:
                for host in ["com.tonec.idm", "com.idm.downloader"]:
                    for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
                        try:
                            winreg.DeleteKey(hive, rf"Software\{browser}\NativeMessagingHosts\{host}")
                        except Exception:
                            pass
            for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
                try:
                    winreg.DeleteKey(hive, r"Software\Mozilla\NativeMessagingHosts\com.idm.downloader")
                except Exception:
                    pass

            self.progress.emit(70, "Removing URL protocol and startup registration...")
            def delete_reg_tree(hive, subkey):
                try:
                    with winreg.OpenKey(hive, subkey, 0, winreg.KEY_ALL_ACCESS) as k:
                        while True:
                            sub = winreg.EnumKey(k, 0)
                            delete_reg_tree(hive, f"{subkey}\\{sub}")
                except OSError:
                    pass
                try:
                    winreg.DeleteKey(hive, subkey)
                except OSError:
                    pass

            for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
                delete_reg_tree(hive, r"Software\Classes\idm")
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
                        winreg.DeleteValue(k, "SimpleDownloader")
                except Exception:
                    pass

                try:
                    winreg.DeleteKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\InternetDownloader")
                except Exception:
                    pass

            self.progress.emit(85, "Removing application files...")
            if self.target_dir and os.path.exists(self.target_dir):
                shutil.rmtree(self.target_dir, ignore_errors=True)

            if self.clean_data:
                self.progress.emit(95, "Cleaning user settings and download queue database...")
                for env_var in ["APPDATA", "LOCALAPPDATA"]:
                    base = os.getenv(env_var)
                    if base:
                        shutil.rmtree(os.path.join(base, "InternetDownloader"), ignore_errors=True)
                        shutil.rmtree(os.path.join(base, "com.idm.downloader"), ignore_errors=True)

            self.progress.emit(100, "Uninstallation completed successfully!")
            self.finished.emit(True, "Complete")
        except Exception as e:
            self.finished.emit(False, str(e))


class ModePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Simple Downloader Setup")
        self.setSubTitle("Select an operation to perform.")

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        lbl = QLabel("Please choose an operation:")
        lbl.setStyleSheet("font-weight: 600; font-size: 11pt; color: #f3f4f6;")
        layout.addWidget(lbl)

        self.btn_group = QButtonGroup(self)

        self.radio_install = QRadioButton("Install Simple Downloader")
        self.radio_install.setChecked(True)
        self.btn_group.addButton(self.radio_install)
        layout.addWidget(self.radio_install)

        desc_install = QLabel("  Installs Simple Downloader fresh to any drive or updates the current install.")
        desc_install.setStyleSheet("color: #94a3b8; font-size: 9pt; margin-left: 24px; margin-bottom: 8px;")
        desc_install.setWordWrap(True)
        layout.addWidget(desc_install)

        self.radio_repair = QRadioButton("Repair / Update Installation")
        self.btn_group.addButton(self.radio_repair)
        layout.addWidget(self.radio_repair)

        desc_repair = QLabel("  Re-verifies all files, fixes broken shortcuts, and restores browser extensions and registry integration.")
        desc_repair.setStyleSheet("color: #94a3b8; font-size: 9pt; margin-left: 24px; margin-bottom: 8px;")
        desc_repair.setWordWrap(True)
        layout.addWidget(desc_repair)

        self.radio_uninstall = QRadioButton("Uninstall Simple Downloader")
        self.btn_group.addButton(self.radio_uninstall)
        layout.addWidget(self.radio_uninstall)

        desc_uninstall = QLabel("  Completely removes Simple Downloader from this computer, removes shortcuts, and cleans up registry settings.")
        desc_uninstall.setStyleSheet("color: #94a3b8; font-size: 9pt; margin-left: 24px;")
        desc_uninstall.setWordWrap(True)
        layout.addWidget(desc_uninstall)

        layout.addStretch()

    def nextId(self):
        if self.radio_uninstall.isChecked():
            return PAGE_UNINSTALL
        return PAGE_DIR


class DirectoryPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Choose Install Location")
        self.setSubTitle("Select destination folder on any drive (C:, D:, etc.)")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        lbl = QLabel("Install Simple Downloader to:")
        lbl.setStyleSheet("font-weight: 600; font-size: 10pt; color: #f3f4f6;")
        layout.addWidget(lbl)

        row = QHBoxLayout()
        self.path_input = QLineEdit(get_default_install_dir())
        row.addWidget(self.path_input, stretch=4)

        browse_btn = QPushButton("Browse...")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.clicked.connect(self._on_browse)
        row.addWidget(browse_btn, stretch=1)
        layout.addLayout(row)

        self.space_lbl = QLabel()
        self.space_lbl.setStyleSheet("color: #94a3b8; font-size: 9pt; line-height: 1.4;")
        layout.addWidget(self.space_lbl)
        self._update_space_info(self.path_input.text())

        self.path_input.textChanged.connect(self._update_space_info)
        layout.addStretch()

    def initializePage(self):
        wizard = self.wizard()
        if wizard and hasattr(wizard, 'mode_page') and wizard.mode_page.radio_repair.isChecked():
            installed = get_installed_dir()
            if installed:
                self.path_input.setText(installed)
                return
        self.path_input.setText(get_default_install_dir())

    def _on_browse(self):
        current = self.path_input.text().strip() or "C:\\"
        folder = QFileDialog.getExistingDirectory(self, "Select Install Directory", current)
        if folder:
            norm = os.path.normpath(folder.replace('/', '\\'))
            if not norm.lower().endswith("simple downloader"):
                norm = os.path.join(norm, "Simple Downloader")
            self.path_input.setText(norm)

    def _update_space_info(self, path: str):
        clean = os.path.normpath(path.strip().replace('/', '\\'))
        drive_letter = os.path.splitdrive(clean)[0] or "C:"
        drive_name = drive_letter.rstrip(':')
        try:
            usage = shutil.disk_usage(drive_letter + "\\")
            free_gb = usage.free / (1024 ** 3)
            self.space_lbl.setText(f"Space Required: ~60 MB\nSpace Available on drive {drive_name}: {free_gb:.1f} GB")
        except Exception:
            self.space_lbl.setText("Space Required: ~60 MB\nSpace Available: Ample")

    def validatePage(self) -> bool:
        raw = self.path_input.text().strip().replace('/', '\\')
        clean_path = os.path.normpath(raw)
        self.path_input.setText(clean_path)

        drive = os.path.splitdrive(clean_path)[0]
        if drive and not os.path.exists(drive + "\\"):
            QMessageBox.warning(
                self,
                "Invalid Drive",
                f"The drive '{drive}' does not exist on this computer.\nPlease select a valid drive (e.g. C:, D:)."
            )
            return False

        return True

    def nextId(self):
        return PAGE_OPTS


class OptionsPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Select Additional Tasks")
        self.setSubTitle("Choose browser integration and shortcut options.")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        self.ext_check = QCheckBox("Register Browser Integration (Chrome, Edge, Brave, Firefox)")
        self.ext_check.setChecked(True)
        layout.addWidget(self.ext_check)

        self.desktop_check = QCheckBox("Create Desktop Shortcut")
        self.desktop_check.setChecked(True)
        layout.addWidget(self.desktop_check)

        self.start_check = QCheckBox("Create Start Menu Shortcut")
        self.start_check.setChecked(True)
        layout.addWidget(self.start_check)

        self.protocol_check = QCheckBox("Register idm:// URL Protocol Handler")
        self.protocol_check.setChecked(True)
        layout.addWidget(self.protocol_check)

        layout.addStretch()

    def nextId(self):
        return PAGE_PROGRESS


class UninstallConfirmPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Confirm Uninstallation")
        self.setSubTitle("Review the installation directory to be removed.")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        self.target_dir = get_installed_dir() or get_default_install_dir()

        self.lbl = QLabel(f"Simple Downloader will be uninstalled from:\n\n{self.target_dir}")
        self.lbl.setStyleSheet("font-size: 10pt; font-weight: 500; color: #f3f4f6;")
        self.lbl.setWordWrap(True)
        layout.addWidget(self.lbl)

        self.clean_data_check = QCheckBox("Also remove user settings, saved download queues, and temporary files")
        self.clean_data_check.setChecked(False)
        layout.addWidget(self.clean_data_check)

        warn_lbl = QLabel("Click Next to begin uninstallation.")
        warn_lbl.setStyleSheet("color: #f87171; font-size: 9pt; font-weight: 500;")
        layout.addWidget(warn_lbl)

        layout.addStretch()

    def initializePage(self):
        self.target_dir = get_installed_dir() or get_default_install_dir()
        self.lbl.setText(f"Simple Downloader will be uninstalled from:\n\n{self.target_dir}")

    def nextId(self):
        return PAGE_PROGRESS


class ProgressPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Executing Requested Operation")
        self.setSubTitle("Please wait while setup completes the task...")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        self.status_lbl = QLabel("Preparing...")
        self.status_lbl.setStyleSheet("font-size: 10pt; font-weight: 500; color: #f3f4f6;")
        layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.worker: Optional[QThread] = None
        self.is_done = False
        layout.addStretch()

    def initializePage(self):
        wizard: 'SimpleDownloaderSetupWizard' = self.wizard()
        mode_page: ModePage = wizard.mode_page

        wizard.button(QWizard.WizardButton.BackButton).setEnabled(False)
        wizard.button(QWizard.WizardButton.NextButton).setEnabled(False)

        if mode_page.radio_uninstall.isChecked():
            target_dir = wizard.uninstall_page.target_dir
            clean_data = wizard.uninstall_page.clean_data_check.isChecked()
            self.setTitle("Uninstalling Simple Downloader")
            self.setSubTitle("Removing application files, shortcuts, and registry entries...")
            self.worker = UninstallWorker(target_dir, clean_data)
        else:
            is_repair = mode_page.radio_repair.isChecked()
            target_dir = wizard.dir_page.path_input.text()
            options = {
                "register_extension": wizard.opts_page.ext_check.isChecked(),
                "desktop_shortcut": wizard.opts_page.desktop_check.isChecked(),
                "start_menu_shortcut": wizard.opts_page.start_check.isChecked(),
                "url_protocol": wizard.opts_page.protocol_check.isChecked()
            }
            title_text = "Repairing Simple Downloader" if is_repair else "Installing Simple Downloader"
            self.setTitle(title_text)
            self.setSubTitle("Copying files, creating shortcuts, and configuring browser extensions...")
            self.worker = InstallWorker(target_dir, options, is_repair)

        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, val: int, msg: str):
        self.progress_bar.setValue(val)
        self.status_lbl.setText(msg)

    def _on_finished(self, success: bool, msg: str):
        if success:
            self.is_done = True
            self.status_lbl.setText("Operation completed successfully!")
            self.wizard().button(QWizard.WizardButton.NextButton).setEnabled(True)
            self.wizard().next()
        else:
            self.is_done = False
            self.status_lbl.setText(f"Installation Failed: {msg}")
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background: #ef4444; }")
            self.wizard().button(QWizard.WizardButton.BackButton).setEnabled(True)
            self.wizard().button(QWizard.WizardButton.CancelButton).setEnabled(True)
            QMessageBox.critical(
                self,
                "Setup Failed",
                f"Setup could not complete the operation:\n\n{msg}\n\n"
                f"Please click '< Back' to choose a different directory or resolve file locks."
            )

    def isComplete(self):
        return self.is_done

    def nextId(self):
        return PAGE_FINISH


class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Setup Completed")
        self.setSubTitle("The operation has finished successfully.")

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(14)

        self.msg_lbl = QLabel()
        self.msg_lbl.setStyleSheet("font-size: 10pt; line-height: 1.5; color: #f3f4f6;")
        self.msg_lbl.setWordWrap(True)
        self.layout.addWidget(self.msg_lbl)

        self.launch_check = QCheckBox("Launch Simple Downloader now")
        self.launch_check.setChecked(True)
        self.layout.addWidget(self.launch_check)

        self.layout.addStretch()

    def initializePage(self):
        wizard: 'SimpleDownloaderSetupWizard' = self.wizard()
        if wizard.mode_page.radio_uninstall.isChecked():
            self.setTitle("Uninstallation Complete")
            self.setSubTitle("Simple Downloader has been completely removed from your PC.")
            self.msg_lbl.setText("All application files, shortcuts, and browser native messaging integrations have been removed cleanly.")
            self.launch_check.setVisible(False)
        elif wizard.mode_page.radio_repair.isChecked():
            self.setTitle("Repair Complete")
            self.setSubTitle("Simple Downloader has been successfully repaired.")
            self.msg_lbl.setText("All core application files, shortcuts, and browser integrations have been refreshed and verified.")
            self.launch_check.setVisible(True)
        else:
            self.setTitle("Installation Complete")
            self.setSubTitle("Simple Downloader is ready to use.")
            self.msg_lbl.setText(
                "Simple Downloader is now ready on your computer.\n\n"
                "• Engine: Multi-Stream Dynamic Segmentation\n"
                "• Native Messaging: Registered for Chrome, Edge, Brave, and Firefox\n"
                "• Acceleration: Pre-allocated disk buffers with zero-lag control"
            )
            self.launch_check.setVisible(True)

    def nextId(self):
        return -1


class SimpleDownloaderSetupWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simple Downloader Setup")
        self.resize(560, 420)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setStyleSheet(get_styled_sheet())

        # Set Window Icon and High-Resolution Logo
        ico = get_app_icon_path()
        if ico and os.path.exists(ico):
            self.setWindowIcon(QIcon(ico))

        png = get_app_png_path()
        if png:
            pix = QPixmap(png).scaled(38, 38, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(QWizard.WizardPixmap.LogoPixmap, pix)
        elif ico and os.path.exists(ico):
            pix = QPixmap(ico).scaled(38, 38, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(QWizard.WizardPixmap.LogoPixmap, pix)

        self.mode_page = ModePage()
        self.dir_page = DirectoryPage()
        self.opts_page = OptionsPage()
        self.uninstall_page = UninstallConfirmPage()
        self.progress_page = ProgressPage()
        self.finish_page = FinishPage()

        self.setPage(PAGE_MODE, self.mode_page)
        self.setPage(PAGE_DIR, self.dir_page)
        self.setPage(PAGE_OPTS, self.opts_page)
        self.setPage(PAGE_UNINSTALL, self.uninstall_page)
        self.setPage(PAGE_PROGRESS, self.progress_page)
        self.setPage(PAGE_FINISH, self.finish_page)

        self.currentIdChanged.connect(self._on_page_changed)
        self.finished.connect(self._on_wizard_finished)

    def _on_page_changed(self, page_id: int):
        for btn_id in [QWizard.WizardButton.NextButton, QWizard.WizardButton.FinishButton]:
            b = self.button(btn_id)
            if b:
                b.setObjectName("primaryWizardBtn")
                b.style().unpolish(b)
                b.style().polish(b)

    def _on_wizard_finished(self, result: int):
        if self.mode_page.radio_uninstall.isChecked():
            return

        if self.finish_page.launch_check.isVisible() and self.finish_page.launch_check.isChecked():
            target_dir = os.path.normpath(self.dir_page.path_input.text().strip().replace('/', '\\'))
            exe = os.path.join(target_dir, "InternetDownloader.exe")
            if os.path.exists(exe):
                try:
                    os.startfile(exe)
                except Exception:
                    import subprocess
                    subprocess.Popen([exe], cwd=target_dir)


def run_installer():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    ico = get_app_icon_path()
    if ico and os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))
    
    app.setStyleSheet(get_styled_sheet())
    wizard = SimpleDownloaderSetupWizard()
    wizard.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_installer()
