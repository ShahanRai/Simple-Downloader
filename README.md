# ⚡ Internet Downloader (Rust + Tauri)

**Internet Downloader** is an executive-grade, ultra-high-performance multi-connection segmented download accelerator and media extraction suite for Windows, built from scratch with **Rust + Tauri v2**.

---

## 📦 Single Windows Installer & Standalone Executable

### 1. Windows Setup Installer (Recommended)
Double-click:
📁 **`Internet_Downloader_Setup.exe`** *(~7.0 MB)*
- Modern Windows Setup Wizard (NSIS).
- Automatically installs to `%LOCALAPPDATA%\Programs\Internet Downloader`.
- Automatically bundles and registers `WebView2Loader.dll`.
- Creates Desktop & Start Menu shortcuts.
- Configures complete Windows uninstaller.

### 2. Standalone Portable Executable
Run directly without installing:
📁 **`InternetDownloader.exe`**
*(Runs side-by-side with `WebView2Loader.dll` in the same directory).*

---

## 🚀 Key Highlights & Architecture

### ⚡ 1. High-Performance Rust Multi-Stream Range Engine
- **RFC 7233 Range-Segmented Acceleration**: Concurrent HTTP connections (1, 2, 4, 8, 16, 24, 32 parallel streams) per file to bypass server single-stream throttling.
- **Dynamic Segment Splitting**: Slower connection threads are dynamically bisected in real time as faster connections finish early, ensuring 100% bandwidth utilization.
- **Resilient Pause & Resume**: Saves atomic state journals (`<filename>.state.json`). Resumes from exact byte offsets without file corruption.
- **Zero-Copy In-Place Disk Writing**: Pre-allocates destination files on disk and streams byte spans directly to their specific byte offsets with zero lock contention.
- **Bandwidth Throttling / Rate Limiter**: Live slider and presets to throttle speed from 256 KB/s to Unlimited.
- **EMA Speed Smoothing**: Exponential moving average smoothed speed gauges and accurate ETA calculations.

### 🎨 2. Executive Neumorphic Desktop UI & UX (Tauri v2)
- **Dual-Shadow Surface Physics**: Soft rounded containers with diffuse dark shadows on the bottom-right and lighting highlights on the top-left.
- **Real-Time Dynamic Connection Stream Visualizer**: Interactive full-width strip displaying each active thread, byte span, dynamic split points, and downloaded ranges with glowing neon blocks!
- **Dark & Light Mode Switcher**: Toggle between Executive Midnight Dark Neumorphism and Soft Platinum Light Neumorphism.
- **Categorized Downloads**: Automatic sorting into **Videos & YouTube**, **Compressed Archives**, **Music**, **Documents**, and **Applications**.
- **Windows Clipboard Sniffer**: Automatically detects copied download URLs and prompts to download.

### 🌐 3. Browser Extension Integration (Chrome, Edge, Brave, Firefox)
- **Embedded Local HTTP API Server**: Runs on `127.0.0.1:9653` with full CORS support so browser extensions can route downloads directly to Internet Downloader.
- **Chrome Web Store Extension Support**: Seamlessly connects with standard browser integration modules.
- **Direct CRX & Unpacked Directory**: Ships with the `browser_extension/` directory ready for 1-click loading in Developer Mode.

---

## 💻 Terminal CLI Mode

Run high-speed accelerated downloads directly from PowerShell or Command Prompt:
```powershell
.\InternetDownloader.exe https://example.com/file.zip -c 16 -o my_download.zip
```

#### CLI Options:
- `-c, --connections <N>`: Parallel stream count (1 to 32, default 16)
- `-o, --output <PATH>`: Destination path or directory
- `-s, --speed-limit <KB>`: Bandwidth throttle in KB/s (0 = unlimited)
- `-h, --help`: Display CLI help
