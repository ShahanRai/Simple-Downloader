use std::collections::VecDeque;
use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use futures_util::StreamExt;
use reqwest::header::{ACCEPT_RANGES, CONTENT_DISPOSITION, CONTENT_LENGTH, CONTENT_TYPE, ETAG, RANGE, USER_AGENT};
use tokio::sync::{mpsc, watch, Mutex, RwLock};
use url::Url;

use crate::model::{DownloadStatus, DownloadTask, ProbeResult, SegmentStatus};

pub const DEFAULT_USER_AGENT: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
pub const MIN_SPLIT_SIZE: u64 = 4 * 1024 * 1024; // 4 MB minimum chunk to justify splitting

/// Global Token-Bucket Rate Limiter shared across downloads and worker streams
#[derive(Clone)]
pub struct SpeedLimiter {
    pub limit_bps: Arc<AtomicU64>,
    state: Arc<Mutex<TokenBucketState>>,
}

struct TokenBucketState {
    tokens: f64,
    last_update: Instant,
}

impl SpeedLimiter {
    pub fn new(limit_bps: u64) -> Self {
        Self {
            limit_bps: Arc::new(AtomicU64::new(limit_bps)),
            state: Arc::new(Mutex::new(TokenBucketState {
                tokens: limit_bps as f64,
                last_update: Instant::now(),
            })),
        }
    }

    pub fn set_limit(&self, limit_bps: u64) {
        self.limit_bps.store(limit_bps, Ordering::Relaxed);
    }

    pub fn get_limit(&self) -> u64 {
        self.limit_bps.load(Ordering::Relaxed)
    }

    /// Throttles download throughput if limit_bps > 0
    pub async fn acquire(&self, bytes: usize) {
        let limit = self.limit_bps.load(Ordering::Relaxed);
        if limit == 0 {
            return;
        }

        let mut state = self.state.lock().await;
        let now = Instant::now();
        let elapsed = (now - state.last_update).as_secs_f64();
        state.last_update = now;

        let max_bucket = (limit as f64).max(65536.0);
        state.tokens = (state.tokens + elapsed * (limit as f64)).min(max_bucket);

        if state.tokens < bytes as f64 {
            let deficit = bytes as f64 - state.tokens;
            let sleep_sec = (deficit / (limit as f64)).min(0.5);
            state.tokens = 0.0;
            drop(state);
            tokio::time::sleep(Duration::from_secs_f64(sleep_sec)).await;
        } else {
            state.tokens -= bytes as f64;
        }
    }
}

/// Probes a remote URL for file metadata, range support, and content size
pub async fn probe_url(client: &reqwest::Client, target_url: &str) -> anyhow::Result<ProbeResult> {
    if target_url.starts_with("magnet:") {
        let mut name = "Torrent_Download.torrent".to_string();
        if let Some(dn_pos) = target_url.find("dn=") {
            let sub = &target_url[dn_pos + 3..];
            let end = sub.find('&').unwrap_or(sub.len());
            let raw_name = &sub[..end];
            let decoded = url::form_urlencoded::parse(format!("v={}", raw_name).as_bytes())
                .next()
                .map(|(_, val)| val.into_owned())
                .unwrap_or_else(|| raw_name.replace('+', " "));
            if !decoded.is_empty() {
                name = decoded;
            }
        }
        if !name.ends_with(".torrent") && !name.contains('.') {
            name = format!("{}.torrent", name);
        }
        return Ok(ProbeResult {
            url: target_url.to_string(),
            filename: crate::model::sanitize_filename(&name),
            file_size: 0,
            accepts_ranges: false,
            etag: None,
            content_type: Some("application/x-bittorrent".to_string()),
        });
    }

    let clean_url = crate::youtube::clean_stream_url(target_url);
    let mut filename = extract_filename_from_url(&clean_url);
    let mut file_size: u64 = 0;
    let mut accepts_ranges = false;
    let mut etag: Option<String> = None;
    let mut content_type: Option<String> = None;

    // Try HEAD request first
    let mut head_builder = client
        .head(&clean_url)
        .header(USER_AGENT, DEFAULT_USER_AGENT)
        .header("Accept", "*/*")
        .header("Accept-Encoding", "identity")
        .header("Connection", "keep-alive");
    if clean_url.contains("googlevideo.com") {
        head_builder = head_builder
            .header("Referer", "https://www.youtube.com/")
            .header("Origin", "https://www.youtube.com");
    }

    let head_res = head_builder.timeout(Duration::from_secs(8)).send().await;

    if let Ok(res) = head_res {
        let headers = res.headers();
        if let Some(ct) = headers.get(CONTENT_TYPE).and_then(|v| v.to_str().ok()) {
            content_type = Some(ct.to_string());
        }
        if let Some(et) = headers.get(ETAG).and_then(|v| v.to_str().ok()) {
            etag = Some(et.to_string());
        }
        if let Some(cd) = headers.get(CONTENT_DISPOSITION).and_then(|v| v.to_str().ok()) {
            if let Some(parsed) = extract_filename_from_disposition(cd) {
                filename = parsed;
            }
        }
        if let Some(ar) = headers.get(ACCEPT_RANGES).and_then(|v| v.to_str().ok()) {
            if ar.to_lowercase().contains("bytes") {
                accepts_ranges = true;
            }
        }
        if let Some(cl) = headers.get(CONTENT_LENGTH).and_then(|v| v.to_str().ok()) {
            if let Ok(val) = cl.parse::<u64>() {
                file_size = val;
            }
        }
    }

    // If size not resolved or ranges unverified, test GET range 0-0
    if file_size == 0 || !accepts_ranges {
        let mut range_builder = client
            .get(&clean_url)
            .header(USER_AGENT, DEFAULT_USER_AGENT)
            .header("Accept", "*/*")
            .header("Accept-Encoding", "identity")
            .header("Connection", "keep-alive")
            .header(RANGE, "bytes=0-0");
        if clean_url.contains("googlevideo.com") {
            range_builder = range_builder
                .header("Referer", "https://www.youtube.com/")
                .header("Origin", "https://www.youtube.com");
        }

        let range_res = range_builder.timeout(Duration::from_secs(10)).send().await;

        if let Ok(res) = range_res {
            let status = res.status();
            let headers = res.headers();

            if status == reqwest::StatusCode::PARTIAL_CONTENT {
                accepts_ranges = true;
                if let Some(cr) = headers.get("content-range").and_then(|v| v.to_str().ok()) {
                    // Content-Range: bytes 0-0/12345
                    if let Some(slash_idx) = cr.rfind('/') {
                        let total_part = &cr[slash_idx + 1..];
                        if let Ok(total) = total_part.trim().parse::<u64>() {
                            file_size = total;
                        }
                    }
                }
            } else if status.is_success() && file_size == 0 {
                if let Some(cl) = headers.get(CONTENT_LENGTH).and_then(|v| v.to_str().ok()) {
                    if let Ok(val) = cl.parse::<u64>() {
                        file_size = val;
                    }
                }
            }

            if let Some(cd) = headers.get(CONTENT_DISPOSITION).and_then(|v| v.to_str().ok()) {
                if let Some(parsed) = extract_filename_from_disposition(cd) {
                    filename = parsed;
                }
            }
        }
    }

    Ok(ProbeResult {
        url: target_url.to_string(),
        filename,
        file_size,
        accepts_ranges,
        etag,
        content_type,
    })
}

fn extract_filename_from_url(url_str: &str) -> String {
    if let Ok(parsed) = Url::parse(url_str) {
        if let Some(segments) = parsed.path_segments() {
            if let Some(last) = segments.last() {
                let clean = last.trim();
                if !clean.is_empty() && clean != "/" {
                    if let Ok(decoded) = urlencoding_decode(clean) {
                        return decoded;
                    }
                    return clean.to_string();
                }
            }
        }
    }
    format!("download_{}", chrono::Utc::now().timestamp())
}

fn extract_filename_from_disposition(disposition: &str) -> Option<String> {
    for part in disposition.split(';') {
        let trimmed = part.trim();
        if trimmed.to_lowercase().starts_with("filename*=") {
            let val = &trimmed[10..];
            let clean = val.trim_matches(|c| c == '\'' || c == '"');
            if let Some(utf8_idx) = clean.to_lowercase().find("utf-8''") {
                let encoded = &clean[utf8_idx + 7..];
                if let Ok(decoded) = urlencoding_decode(encoded) {
                    return Some(decoded);
                }
            }
        } else if trimmed.to_lowercase().starts_with("filename=") {
            let val = &trimmed[9..];
            let clean = val.trim_matches(|c| c == '\'' || c == '"').trim();
            if !clean.is_empty() {
                return Some(clean.to_string());
            }
        }
    }
    None
}

fn urlencoding_decode(s: &str) -> Result<String, ()> {
    url::form_urlencoded::parse(s.as_bytes())
        .next()
        .map(|(k, _)| k.to_string())
        .ok_or(())
}

/// Dynamic Segment Splitting & Multi-Stream Acceleration Downloader
pub struct SegmentDownloader {
    pub task: Arc<RwLock<DownloadTask>>,
    pub client: reqwest::Client,
    pub stop_tx: watch::Sender<bool>,
    pub stop_rx: watch::Receiver<bool>,
    pub speed_limiter: SpeedLimiter,
}

impl SegmentDownloader {
    pub fn new(task: DownloadTask, client: reqwest::Client, speed_limiter: SpeedLimiter) -> (Self, watch::Sender<bool>) {
        let (stop_tx, stop_rx) = watch::channel(false);
        let task_arc = Arc::new(RwLock::new(task));
        (
            Self {
                task: task_arc,
                client,
                stop_tx: stop_tx.clone(),
                stop_rx,
                speed_limiter,
            },
            stop_tx,
        )
    }

    pub async fn run(&self, on_progress: mpsc::Sender<DownloadTask>) -> anyhow::Result<()> {
        let mut task = self.task.read().await.clone();
        let target_url = task.url.clone();
        let output_path = PathBuf::from(&task.output_path);

        // Ensure parent folder exists
        if let Some(parent) = output_path.parent() {
            let _ = tokio::fs::create_dir_all(parent).await;
        }

        // Ensure destination file is created and pre-allocated upfront
        let out_clone = output_path.clone();
        let expected_size = task.file_size;
        tokio::task::spawn_blocking(move || -> std::io::Result<()> {
            let f = OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(false)
                .open(&out_clone)?;
            if expected_size > 0 {
                let _ = f.set_len(expected_size);
            }
            Ok(())
        })
        .await??;

        // Ensure segments are populated if empty
        if task.segments.is_empty() {
            task.segments = DownloadTask::create_segments(task.file_size, task.connections);
            task.save_state();
            *self.task.write().await = task.clone();
        }

        // Launch worker threads for each segment
        let segments_len = task.segments.len();
        let mut join_handles = Vec::new();

        let bytes_counter = Arc::new(std::sync::atomic::AtomicU64::new(task.downloaded_bytes));

        for seg_idx in 0..segments_len {
            let task_lock = self.task.clone();
            let client = self.client.clone();
            let url = target_url.clone();
            let path = output_path.clone();
            let mut stop_rx = self.stop_rx.clone();
            let bytes_acc = bytes_counter.clone();
            let limiter = self.speed_limiter.clone();

            let handle = tokio::spawn(async move {
                Self::download_segment(seg_idx, task_lock, client, url, path, &mut stop_rx, bytes_acc, limiter).await
            });
            join_handles.push(handle);
        }

        // Progress & Dynamic Coordinator Loop
        let mut ticker = tokio::time::interval(Duration::from_millis(250));
        let mut last_save = Instant::now();
        let mut speed_samples: VecDeque<f64> = VecDeque::with_capacity(8);
        let mut speed_calc_time = Instant::now();
        let mut speed_calc_bytes: u64 = task.downloaded_bytes;

        loop {
            tokio::select! {
                _ = ticker.tick() => {
                    if *self.stop_rx.borrow() {
                        break;
                    }

                    let mut current = self.task.write().await;
                    let now = Instant::now();

                    // Calculate downloaded bytes across segments
                    let current_downloaded: u64 = current.segments.iter().map(|s| s.downloaded_bytes()).sum();
                    current.downloaded_bytes = current_downloaded;

                    // Only recalculate speed every 1.0 second for stability
                    let speed_elapsed = speed_calc_time.elapsed().as_secs_f64();
                    if speed_elapsed >= 1.0 {
                        let diff = current_downloaded.saturating_sub(speed_calc_bytes);
                        let sample = diff as f64 / speed_elapsed;
                        if speed_samples.len() >= 8 { speed_samples.pop_front(); }
                        speed_samples.push_back(sample);
                        let avg = speed_samples.iter().sum::<f64>() / speed_samples.len() as f64;
                        current.speed_bps = avg;
                        if avg > 0.0 && current.file_size > current_downloaded {
                            current.eta_seconds = (current.file_size - current_downloaded) as f64 / avg;
                        } else {
                            current.eta_seconds = 0.0;
                        }
                        speed_calc_time = now;
                        speed_calc_bytes = current_downloaded;
                    }

                    // Save state periodically (every 4 seconds) to avoid heavy disk thrashing
                    if now.duration_since(last_save).as_secs() >= 4 {
                        current.save_state();
                        last_save = now;
                    }

                    // Check completion or failure
                    let all_completed = if current.file_size > 0 {
                        current.segments.iter().all(|s| s.status == SegmentStatus::COMPLETED || s.remaining_bytes() == 0)
                    } else {
                        current.segments.iter().all(|s| s.status == SegmentStatus::COMPLETED) && current_downloaded > 0
                    };
                    let all_stopped = current.segments.iter().all(|s| s.status == SegmentStatus::COMPLETED || s.status == SegmentStatus::FAILED || s.status == SegmentStatus::PAUSED);

                    if all_completed || (current.file_size > 0 && current_downloaded >= current.file_size) {
                        current.status = DownloadStatus::COMPLETED;
                        current.downloaded_bytes = current.file_size.max(current_downloaded);
                        current.completed_at = Some(chrono::Utc::now().timestamp() as f64);
                        current.speed_bps = 0.0;
                        current.save_state();
                        let _ = on_progress.send(current.clone()).await;
                        break;
                    } else if all_stopped {
                        let has_failed = current.segments.iter().any(|s| s.status == SegmentStatus::FAILED);
                        if has_failed {
                            current.status = DownloadStatus::FAILED;
                            current.error_message = Some("Download interrupted. Click Resume to retry.".to_string());
                            current.speed_bps = 0.0;
                            current.save_state();
                            let _ = on_progress.send(current.clone()).await;
                            break;
                        }
                    }

                    let _ = on_progress.send(current.clone()).await;
                }
            }
        }

        // Wait for workers to clean up
        for handle in join_handles {
            let _ = handle.await;
        }

        let mut final_task = self.task.write().await;
        if final_task.status != DownloadStatus::COMPLETED && final_task.status != DownloadStatus::FAILED {
            final_task.status = DownloadStatus::PAUSED;
            final_task.speed_bps = 0.0;
        }
        final_task.save_state();
        let _ = on_progress.send(final_task.clone()).await;

        Ok(())
    }

    /// Downloads an individual segment chunk with retries and writes directly to disk offset
    async fn download_segment(
        seg_idx: usize,
        task_lock: Arc<RwLock<DownloadTask>>,
        client: reqwest::Client,
        url: String,
        output_path: PathBuf,
        stop_rx: &mut watch::Receiver<bool>,
        bytes_counter: Arc<std::sync::atomic::AtomicU64>,
        speed_limiter: SpeedLimiter,
    ) -> anyhow::Result<()> {
        let (_start_byte, end_byte, mut current_byte) = {
            let task = task_lock.read().await;
            if seg_idx >= task.segments.len() {
                return Ok(());
            }
            let seg = &task.segments[seg_idx];
            if seg.status == SegmentStatus::COMPLETED || seg.remaining_bytes() == 0 {
                return Ok(());
            }
            (seg.start_byte, seg.end_byte, seg.current_byte)
        };

        {
            let mut task = task_lock.write().await;
            task.segments[seg_idx].status = SegmentStatus::DOWNLOADING;
        }

        let mut retries = 0;
        let max_retries = 3;

        while current_byte <= end_byte || (end_byte == 0 && current_byte == 0) {
            if *stop_rx.borrow() {
                let mut task = task_lock.write().await;
                task.segments[seg_idx].status = SegmentStatus::PAUSED;
                task.segments[seg_idx].current_byte = current_byte;
                return Ok(());
            }

            let clean_url = crate::youtube::clean_stream_url(&url);
            let mut request = client
                .get(&clean_url)
                .header(USER_AGENT, DEFAULT_USER_AGENT)
                .header("Accept", "*/*")
                .header("Accept-Language", "en-US,en;q=0.9")
                .header("Accept-Encoding", "identity")
                .header("Connection", "keep-alive")
                .header("Sec-Fetch-Dest", "empty")
                .header("Sec-Fetch-Mode", "cors")
                .header("Sec-Fetch-Site", "cross-site");
            if clean_url.contains("googlevideo.com") {
                request = request
                    .header("Referer", "https://www.youtube.com/")
                    .header("Origin", "https://www.youtube.com");
            }

            if end_byte > 0 && end_byte >= current_byte {
                request = request.header(RANGE, format!("bytes={}-{}", current_byte, end_byte));
            } else if current_byte > 0 {
                request = request.header(RANGE, format!("bytes={}-", current_byte));
            }

            let response = match request.send().await {
                Ok(res) if res.status().is_success() || res.status() == reqwest::StatusCode::PARTIAL_CONTENT => res,
                Ok(res) => {
                    if retries < max_retries {
                        retries += 1;
                        tokio::time::sleep(Duration::from_millis(500 * retries as u64)).await;
                        continue;
                    }
                    let mut task = task_lock.write().await;
                    task.segments[seg_idx].status = SegmentStatus::FAILED;
                    return Err(anyhow::anyhow!("HTTP error: {}", res.status()));
                }
                Err(e) => {
                    if retries < max_retries {
                        retries += 1;
                        tokio::time::sleep(Duration::from_millis(500 * retries as u64)).await;
                        continue;
                    }
                    let mut task = task_lock.write().await;
                    task.segments[seg_idx].status = SegmentStatus::FAILED;
                    return Err(e.into());
                }
            };

            // Open destination file for buffered writing
            let raw_file = match OpenOptions::new().write(true).open(&output_path) {
                Ok(f) => f,
                Err(e) => {
                    let mut task = task_lock.write().await;
                    task.segments[seg_idx].status = SegmentStatus::FAILED;
                    return Err(e.into());
                }
            };

            let mut file = std::io::BufWriter::with_capacity(256 * 1024, raw_file);
            if let Err(e) = file.seek(SeekFrom::Start(current_byte)) {
                let mut task = task_lock.write().await;
                task.segments[seg_idx].status = SegmentStatus::FAILED;
                return Err(e.into());
            }

            let mut stream = response.bytes_stream();
            let mut seg_last_time = Instant::now();
            let mut seg_last_bytes = current_byte;
            let mut stream_interrupted = false;

            while let Some(chunk_res) = stream.next().await {
                if *stop_rx.borrow() {
                    let _ = file.flush();
                    let mut task = task_lock.write().await;
                    task.segments[seg_idx].status = SegmentStatus::PAUSED;
                    task.segments[seg_idx].current_byte = current_byte;
                    return Ok(());
                }

                match chunk_res {
                    Ok(chunk) => {
                        // Global speed limiter token bucket acquisition
                        speed_limiter.acquire(chunk.len()).await;

                        if let Err(e) = file.write_all(&chunk) {
                            let mut task = task_lock.write().await;
                            task.segments[seg_idx].status = SegmentStatus::FAILED;
                            return Err(e.into());
                        }

                        let len = chunk.len() as u64;
                        current_byte += len;
                        bytes_counter.fetch_add(len, Ordering::Relaxed);

                        let now = Instant::now();
                        let dt = (now - seg_last_time).as_secs_f64();
                        if dt >= 0.5 {
                            let seg_speed = (current_byte - seg_last_bytes) as f64 / dt;
                            if let Ok(mut task) = task_lock.try_write() {
                                task.segments[seg_idx].current_byte = current_byte;
                                task.segments[seg_idx].speed_bps = seg_speed;
                            }
                            seg_last_time = now;
                            seg_last_bytes = current_byte;
                        }

                        if end_byte > 0 && current_byte > end_byte {
                            let _ = file.flush();
                            break;
                        }
                    }
                    Err(_) => {
                        stream_interrupted = true;
                        break;
                    }
                }
            }

            if stream_interrupted {
                if retries < max_retries {
                    retries += 1;
                    tokio::time::sleep(Duration::from_millis(500 * retries as u64)).await;
                    continue;
                } else {
                    let mut task = task_lock.write().await;
                    task.segments[seg_idx].status = SegmentStatus::FAILED;
                    task.segments[seg_idx].current_byte = current_byte;
                    return Err(anyhow::anyhow!("Stream interrupted after retries"));
                }
            }

            break;
        }

        // Segment completed
        {
            let mut task = task_lock.write().await;
            task.segments[seg_idx].current_byte = current_byte;
            task.segments[seg_idx].status = SegmentStatus::COMPLETED;
            task.segments[seg_idx].speed_bps = 0.0;
        }

        Ok(())
    }
}
