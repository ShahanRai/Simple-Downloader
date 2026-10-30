use arboard::Clipboard;
use std::time::Duration;
use tauri::{AppHandle, Emitter};

pub fn start_clipboard_monitor(app_handle: AppHandle) {
    std::thread::spawn(move || {
        let mut last_clipboard = String::new();
        let monitored_extensions = [
            ".zip", ".rar", ".7z", ".tar", ".gz", ".iso", ".dmg",
            ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv",
            ".mp3", ".wav", ".flac", ".aac",
            ".pdf", ".epub", ".docx", ".xlsx",
            ".exe", ".msi", ".apk", ".bin"
        ];

        loop {
            std::thread::sleep(Duration::from_millis(1000));

            if let Ok(mut clipboard) = Clipboard::new() {
                if let Ok(text) = clipboard.get_text() {
                    let trimmed = text.trim();
                    if trimmed != last_clipboard && (trimmed.starts_with("http://") || trimmed.starts_with("https://")) {
                        last_clipboard = trimmed.to_string();

                        let lower = trimmed.to_lowercase();
                        let clean = lower.split('?').next().unwrap_or("").split('#').next().unwrap_or("");
                        let matches_ext = monitored_extensions.iter().any(|ext| clean.ends_with(ext));
                        let is_media = lower.contains("youtube.com/watch") || lower.contains("youtu.be/") || lower.contains("vimeo.com/");

                        if matches_ext || is_media {
                            let _ = app_handle.emit("clipboard-download-detected", serde_json::json!({
                                "url": trimmed,
                                "is_media": is_media
                            }));
                        }
                    }
                }
            }
        }
    });
}

