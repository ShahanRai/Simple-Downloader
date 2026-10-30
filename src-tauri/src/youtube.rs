use std::path::PathBuf;
use std::process::Command;
use url::Url;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug)]
pub struct YouTubeFormatItem {
    pub id: String,
    pub quality: String,
    pub format: String,
    pub size: u64,
    pub url: String,
    pub is_audio: bool,
    pub order: i32,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug)]
pub struct YouTubeResolveResult {
    pub title: String,
    pub formats: Vec<YouTubeFormatItem>,
}

pub fn is_youtube_url(url: &str) -> bool {
    url.contains("youtube.com/watch")
        || url.contains("youtu.be/")
        || url.contains("youtube.com/shorts/")
        || url.contains("youtube.com/live/")
}

/// Strips range and segment query parameters from googlevideo URLs
pub fn clean_stream_url(url_str: &str) -> String {
    if url_str.contains("googlevideo.com") {
        if let Ok(mut parsed) = Url::parse(url_str) {
            let pairs: Vec<(String, String)> = parsed
                .query_pairs()
                .filter(|(k, _)| k != "range" && k != "rn" && k != "rbuf")
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect();
            parsed.query_pairs_mut().clear().extend_pairs(pairs);
            return parsed.to_string();
        }
    }
    url_str.to_string()
}

static CACHED_YTDLP: std::sync::OnceLock<Option<PathBuf>> = std::sync::OnceLock::new();

/// Locates yt-dlp binary on the system without spawning any console windows
pub fn find_ytdlp() -> Option<PathBuf> {
    CACHED_YTDLP
        .get_or_init(|| {
            // 1. Direct path check from PATH environment variable (zero subprocesses, no console flash)
            if let Some(path_var) = std::env::var_os("PATH") {
                for dir in std::env::split_paths(&path_var) {
                    let candidate = dir.join("yt-dlp.exe");
                    if candidate.is_file() {
                        return Some(candidate);
                    }
                    let candidate_py = dir.join("yt-dlp");
                    if candidate_py.is_file() {
                        return Some(candidate_py);
                    }
                }
            }

            // 2. Check AppData Python Scripts
            if let Ok(appdata) = std::env::var("APPDATA") {
                let python_dir = PathBuf::from(appdata).join("Python");
                if python_dir.exists() {
                    if let Ok(entries) = std::fs::read_dir(&python_dir) {
                        for entry in entries.flatten() {
                            let candidate = entry.path().join("Scripts").join("yt-dlp.exe");
                            if candidate.is_file() {
                                return Some(candidate);
                            }
                        }
                    }
                }
            }

            // 3. Check LocalAppData Programs Python
            if let Ok(local) = std::env::var("LOCALAPPDATA") {
                let py_programs = PathBuf::from(local).join("Programs").join("Python");
                if py_programs.exists() {
                    if let Ok(entries) = std::fs::read_dir(&py_programs) {
                        for entry in entries.flatten() {
                            let candidate = entry.path().join("Scripts").join("yt-dlp.exe");
                            if candidate.is_file() {
                                return Some(candidate);
                            }
                        }
                    }
                }
            }

            // 4. Same directory as current executable
            if let Ok(exe) = std::env::current_exe() {
                if let Some(parent) = exe.parent() {
                    let candidate = parent.join("yt-dlp.exe");
                    if candidate.is_file() {
                        return Some(candidate);
                    }
                }
            }

            None
        })
        .clone()
}

/// Resolves video formats from a YouTube page URL via yt-dlp
pub fn resolve_youtube(target_url: &str) -> anyhow::Result<YouTubeResolveResult> {
    let ytdlp_bin = find_ytdlp().ok_or_else(|| anyhow::anyhow!("yt-dlp binary not found on system"))?;

    let mut cmd = Command::new(&ytdlp_bin);
    cmd.arg("-j")
        .arg("--no-warnings")
        .arg("--no-playlist")
        .arg(target_url);

    cmd.stdin(std::process::Stdio::null());
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());

    #[cfg(target_os = "windows")]
    {
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let output = cmd.output()?;
    if !output.status.success() {
        let err = String::from_utf8_lossy(&output.stderr);
        return Err(anyhow::anyhow!("yt-dlp error: {}", err));
    }

    let json_str = String::from_utf8_lossy(&output.stdout);
    let val: serde_json::Value = serde_json::from_str(&json_str)?;

    let title = val["title"].as_str().unwrap_or("YouTube Video").to_string();
    let mut items: Vec<YouTubeFormatItem> = Vec::new();

    if let Some(formats) = val["formats"].as_array() {
        // Collect best format candidates with valid direct URLs and real byte sizes
        for f in formats {
            let url_opt = f["url"].as_str();
            if url_opt.is_none() {
                continue;
            }
            let raw_url = clean_stream_url(url_opt.unwrap());
            if raw_url.contains(".m3u8") || f["protocol"].as_str().unwrap_or("").contains("m3u8") {
                continue;
            }

            let format_id = f["format_id"].as_str().unwrap_or("").to_string();
            let ext = f["ext"].as_str().unwrap_or("mp4").to_lowercase();
            let height = f["height"].as_u64();
            let width = f["width"].as_u64();
            let note = f["format_note"].as_str().unwrap_or("").to_lowercase();
            let size = f["filesize"].as_u64().or_else(|| f["filesize_approx"].as_u64()).unwrap_or(0);
            let acodec = f["acodec"].as_str().unwrap_or("none");
            let vcodec = f["vcodec"].as_str().unwrap_or("none");

            if ext == "mhtml" || size == 0 {
                continue;
            }

            if vcodec != "none" && (ext == "mp4" || ext == "webm") {
                let h = height.unwrap_or(0);
                let w = width.unwrap_or(0);

                let (quality, order) = if note.contains("1080") || h >= 900 || w >= 1900 {
                    ("1080p Full HD", 1)
                } else if note.contains("720") || h >= 600 || w >= 1200 {
                    ("720p HD", 2)
                } else if note.contains("480") || h >= 400 || w >= 800 {
                    ("480p", 3)
                } else if note.contains("360") || h >= 300 || w >= 600 {
                    ("360p", 4)
                } else if note.contains("240") || h >= 200 || w >= 400 {
                    ("240p", 5)
                } else {
                    continue;
                };

                let format_label = if ext == "webm" { "WebM" } else { "MP4" };

                // Prefer MP4 or higher file size for each tier
                if let Some(existing) = items.iter_mut().find(|it| it.quality == quality && it.format == format_label) {
                    if size > existing.size {
                        existing.id = format_id;
                        existing.size = size;
                        existing.url = raw_url;
                    }
                } else {
                    items.push(YouTubeFormatItem {
                        id: format_id,
                        quality: quality.to_string(),
                        format: format_label.to_string(),
                        size,
                        url: raw_url,
                        is_audio: false,
                        order,
                    });
                }
            } else if acodec != "none" && vcodec == "none" {
                // Audio stream
                let is_m4a = ext == "m4a" || ext == "mp4";
                let quality = if is_m4a { "Audio (M4A)" } else { "Audio (Opus)" };
                let format_label = if is_m4a { "M4A" } else { "WebM" };
                let order = if is_m4a { 10 } else { 11 };

                if let Some(existing) = items.iter_mut().find(|it| it.quality == quality) {
                    if size > existing.size {
                        existing.id = format_id;
                        existing.size = size;
                        existing.url = raw_url;
                    }
                } else {
                    items.push(YouTubeFormatItem {
                        id: format_id,
                        quality: quality.to_string(),
                        format: format_label.to_string(),
                        size,
                        url: raw_url,
                        is_audio: true,
                        order,
                    });
                }
            }
        }
    }

    items.sort_by_key(|it| it.order);

    Ok(YouTubeResolveResult {
        title,
        formats: items,
    })
}

