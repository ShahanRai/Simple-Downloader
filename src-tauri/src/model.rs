use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum DownloadStatus {
    INITIALIZING,
    PENDING,
    QUEUED,
    DOWNLOADING,
    PAUSED,
    COMPLETED,
    FAILED,
    CANCELLED,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum SegmentStatus {
    PENDING,
    DOWNLOADING,
    COMPLETED,
    PAUSED,
    FAILED,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Segment {
    pub id: usize,
    pub start_byte: u64,
    pub end_byte: u64,
    pub current_byte: u64,
    pub status: SegmentStatus,
    pub speed_bps: f64,
}

impl Segment {
    pub fn new(id: usize, start: u64, end: u64) -> Self {
        Self {
            id,
            start_byte: start,
            end_byte: end,
            current_byte: start,
            status: SegmentStatus::PENDING,
            speed_bps: 0.0,
        }
    }

    pub fn total_bytes(&self) -> u64 {
        if self.end_byte >= self.start_byte {
            self.end_byte - self.start_byte + 1
        } else {
            0
        }
    }

    pub fn downloaded_bytes(&self) -> u64 {
        if self.current_byte >= self.start_byte {
            (self.current_byte - self.start_byte).min(self.total_bytes())
        } else {
            0
        }
    }

    pub fn remaining_bytes(&self) -> u64 {
        if self.end_byte >= self.current_byte {
            self.end_byte - self.current_byte + 1
        } else {
            0
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DownloadTask {
    pub id: String,
    pub url: String,
    pub output_path: String,
    pub filename: String,
    pub file_size: u64,
    pub downloaded_bytes: u64,
    pub status: DownloadStatus,
    pub connections: usize,
    pub max_speed_bps: f64,
    pub speed_bps: f64,
    pub eta_seconds: f64,
    pub category: String,
    pub created_at: f64,
    pub completed_at: Option<f64>,
    pub error_message: Option<String>,
    pub segments: Vec<Segment>,
}

impl DownloadTask {
    pub fn progress_pct(&self) -> f64 {
        if self.file_size == 0 {
            if self.status == DownloadStatus::COMPLETED { 100.0 } else { 0.0 }
        } else {
            ((self.downloaded_bytes as f64 / self.file_size as f64) * 100.0).min(100.0)
        }
    }

    pub fn create_segments(file_size: u64, num_conns: usize) -> Vec<Segment> {
        let n = num_conns.clamp(1, 32) as u64;
        if file_size > 0 && n > 1 {
            let part_size = file_size / n;
            let mut segments = Vec::new();
            for i in 0..n {
                let start = i * part_size;
                let end = if i == n - 1 {
                    file_size - 1
                } else {
                    (i + 1) * part_size - 1
                };
                segments.push(Segment::new(i as usize, start, end));
            }
            segments
        } else {
            vec![Segment::new(0, 0, if file_size > 0 { file_size - 1 } else { 0 })]
        }
    }

    pub fn state_path(&self) -> PathBuf {
        PathBuf::from(format!("{}.state.json", self.output_path))
    }

    pub fn save_state(&self) {
        let state_file = self.state_path();
        let tmp_file = PathBuf::from(format!("{}.state.json.tmp", self.output_path));
        if let Ok(json_str) = serde_json::to_string_pretty(self) {
            let _ = fs::write(&tmp_file, json_str);
            let _ = fs::rename(&tmp_file, &state_file);
        }
    }

    pub fn load_state<P: AsRef<Path>>(path: P) -> Option<Self> {
        let state_file = format!("{}.state.json", path.as_ref().to_string_lossy());
        if let Ok(content) = fs::read_to_string(&state_file) {
            serde_json::from_str(&content).ok()
        } else {
            None
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProbeResult {
    pub url: String,
    pub filename: String,
    pub file_size: u64,
    pub accepts_ranges: bool,
    pub etag: Option<String>,
    pub content_type: Option<String>,
}

pub fn sanitize_filename(name: &str) -> String {
    let invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*'];
    let clean: String = name
        .chars()
        .map(|c| if invalid_chars.contains(&c) { '_' } else { c })
        .collect();
    let trimmed = clean.trim().trim_matches('.').to_string();
    if trimmed.is_empty() {
        format!("download_{}", chrono::Utc::now().timestamp())
    } else {
        trimmed
    }
}

pub fn infer_category(filename: &str) -> &'static str {
    let lower = filename.to_lowercase();
    let ext = Path::new(&lower).extension().and_then(|e| e.to_str()).unwrap_or("");
    match ext {
        "zip" | "rar" | "7z" | "tar" | "gz" | "bz2" | "xz" | "iso" | "dmg" => "Compressed",
        "mp4" | "mkv" | "webm" | "avi" | "mov" | "flv" | "wmv" | "m4v" => "Video",
        "mp3" | "wav" | "flac" | "aac" | "ogg" | "m4a" | "opus" => "Music",
        "pdf" | "doc" | "docx" | "xls" | "xlsx" | "ppt" | "pptx" | "txt" | "epub" => "Documents",
        "exe" | "msi" | "bat" | "cmd" | "apk" | "jar" | "appx" => "Programs",
        _ => "General",
    }
}

