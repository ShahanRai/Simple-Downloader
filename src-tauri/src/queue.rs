use std::collections::HashMap;
use std::collections::HashSet;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::{mpsc, watch, RwLock};

use crate::engine::{probe_url, SegmentDownloader, SpeedLimiter};
use crate::model::{infer_category, DownloadStatus, DownloadTask};
use crate::youtube::{clean_stream_url, is_youtube_url, resolve_youtube};

pub struct QueueManager {
    pub tasks: HashMap<String, DownloadTask>,
    pub downloaders: HashMap<String, watch::Sender<bool>>,
    pub client: reqwest::Client,
    pub db_path: PathBuf,
    pub default_download_dir: PathBuf,
    pub max_active_tasks: usize,
    pub global_speed_limit_bps: f64,
    pub speed_limiter: SpeedLimiter,
    pub progress_tx: mpsc::Sender<DownloadTask>,
    pub cancelled_ids: HashSet<String>,
}

impl QueueManager {
    pub fn new(progress_tx: mpsc::Sender<DownloadTask>) -> Self {
        let app_data = std::env::var("APPDATA").unwrap_or_else(|_| ".".to_string());
        let storage_dir = PathBuf::from(app_data).join("InternetDownloader");
        let _ = fs::create_dir_all(&storage_dir);

        let db_path = storage_dir.join("tasks_queue.json");

        let default_download_dir = dirs_next_download_dir().unwrap_or_else(|| {
            let home = std::env::var("USERPROFILE").unwrap_or_else(|_| ".".to_string());
            PathBuf::from(home).join("Downloads")
        });
        let _ = fs::create_dir_all(&default_download_dir);

        let mut qm = Self {
            tasks: HashMap::new(),
            downloaders: HashMap::new(),
            client: reqwest::Client::builder()
                .pool_max_idle_per_host(64)
                .pool_idle_timeout(std::time::Duration::from_secs(90))
                .tcp_keepalive(std::time::Duration::from_secs(60))
                .tcp_nodelay(true)
                .connect_timeout(std::time::Duration::from_secs(12))
                .build()
                .unwrap_or_default(),
            db_path,
            default_download_dir,
            max_active_tasks: 4,
            global_speed_limit_bps: 0.0,
            speed_limiter: SpeedLimiter::new(0),
            progress_tx,
            cancelled_ids: HashSet::new(),
        };

        qm.load_from_disk();
        qm
    }

    pub fn load_from_disk(&mut self) {
        if self.db_path.exists() {
            if let Ok(content) = fs::read_to_string(&self.db_path) {
                if let Ok(loaded) = serde_json::from_str::<Vec<DownloadTask>>(&content) {
                    for mut t in loaded {
                        // Mark active tasks as paused upon app startup
                        if t.status == DownloadStatus::DOWNLOADING || t.status == DownloadStatus::INITIALIZING {
                            t.status = DownloadStatus::PAUSED;
                        }
                        self.tasks.insert(t.id.clone(), t);
                    }
                }
            }
        }
    }

    pub fn save_to_disk(&self) {
        let list: Vec<DownloadTask> = self.tasks.values().cloned().collect();
        if let Ok(json) = serde_json::to_string_pretty(&list) {
            let tmp_path = self.db_path.with_extension("tmp");
            let _ = fs::write(&tmp_path, json);
            let _ = fs::rename(&tmp_path, &self.db_path);
        }
    }

    pub fn get_all_tasks(&self) -> Vec<DownloadTask> {
        let mut list: Vec<DownloadTask> = self.tasks.values().cloned().collect();
        list.sort_by(|a, b| b.created_at.partial_cmp(&a.created_at).unwrap_or(std::cmp::Ordering::Equal));
        list
    }

    pub async fn add_task(
        qm_arc: Arc<RwLock<Self>>,
        url: String,
        connections: Option<usize>,
        auto_start: bool,
        custom_output_path: Option<String>,
    ) -> anyhow::Result<DownloadTask> {
        // Reject blob URLs - they are browser internal memory buffers
        if url.starts_with("blob:") {
            return Err(anyhow::anyhow!("Blob URLs are temporary browser buffers. Please click the IDM extension button and choose a video quality stream."));
        }

        // Magnet Link Integration: in-app downloading without launching external clients
        if url.starts_with("magnet:") {
            let probe = crate::torrent::probe_magnet(&url);

            let default_dir = { qm_arc.read().await.default_download_dir.clone() };
            let out_dir = custom_output_path.map(PathBuf::from).unwrap_or(default_dir);
            let final_output = out_dir.join(&probe.filename);

            let task_id = uuid::Uuid::new_v4().to_string()[..8].to_string();
            let (stop_tx, stop_rx) = watch::channel(false);

            let task = DownloadTask {
                id: task_id.clone(),
                url: url.clone(),
                output_path: final_output.to_string_lossy().to_string(),
                filename: probe.filename,
                file_size: probe.file_size,
                downloaded_bytes: 0,
                status: if auto_start { DownloadStatus::DOWNLOADING } else { DownloadStatus::PAUSED },
                connections: connections.unwrap_or(16).clamp(1, 32),
                max_speed_bps: 0.0,
                speed_bps: 0.0,
                eta_seconds: 0.0,
                category: "Compressed".to_string(),
                created_at: chrono::Utc::now().timestamp() as f64,
                completed_at: None,
                error_message: None,
                segments: vec![],
            };

            {
                let mut qm = qm_arc.write().await;
                qm.tasks.insert(task_id.clone(), task.clone());
                if auto_start {
                    qm.downloaders.insert(task_id.clone(), stop_tx);
                }
                qm.save_to_disk();
            }

            if auto_start {
                let task_clone = task.clone();
                let qm_clone = qm_arc.clone();
                tokio::spawn(async move {
                    crate::torrent::start_torrent_task(task_clone, qm_clone, stop_rx).await;
                });
            }

            return Ok(task);
        }

        // Clean query strings & resolve YouTube URLs if needed
        let mut download_url = clean_stream_url(&url);
        let mut resolved_title: Option<String> = None;

        if is_youtube_url(&download_url) {
            match tokio::task::spawn_blocking({
                let u = download_url.clone();
                move || resolve_youtube(&u)
            }).await? {
                Ok(res) => {
                    resolved_title = Some(res.title.clone());
                    if let Some(best) = res.formats.first() {
                        download_url = best.url.clone();
                    }
                }
                Err(e) => {
                    return Err(anyhow::anyhow!("Failed to resolve YouTube video: {}. Ensure yt-dlp is available.", e));
                }
            }
        }

        let client = { qm_arc.read().await.client.clone() };
        let probe = probe_url(&client, &download_url).await?;

        // Reject HTML pages - not downloadable files
        if let Some(ref ct) = probe.content_type {
            let ct_lower = ct.to_lowercase();
            if ct_lower.contains("text/html") || ct_lower.contains("application/xhtml") {
                return Err(anyhow::anyhow!("This URL points to a web page, not a downloadable file. Please use a direct download link."));
            }
        }

        let mut qm = qm_arc.write().await;

        // Check for duplicate active downloads
        for existing in qm.tasks.values() {
            if (existing.url == download_url || existing.url == url) && existing.status != DownloadStatus::COMPLETED && existing.status != DownloadStatus::CANCELLED {
                return Err(anyhow::anyhow!("This URL is already in the download queue. Pause or delete it first."));
            }
        }

        let mut filename = if let Some(ref t) = resolved_title {
            format!("{}.mp4", crate::model::sanitize_filename(t))
        } else {
            crate::model::sanitize_filename(&probe.filename)
        };

        let output_path = if let Some(custom) = custom_output_path.filter(|s| !s.trim().is_empty()) {
            let p = PathBuf::from(&custom);
            if p.is_dir() {
                p.join(&filename)
            } else if p.is_relative() {
                if let Some(name) = p.file_name().and_then(|n| n.to_str()) {
                    filename = crate::model::sanitize_filename(name);
                }
                qm.default_download_dir.join(&filename)
            } else {
                if let Some(name) = p.file_name().and_then(|n| n.to_str()) {
                    filename = crate::model::sanitize_filename(name);
                }
                p
            }
        } else {
            qm.default_download_dir.join(&filename)
        };

        let category = infer_category(&filename).to_string();

        let task_id = uuid::Uuid::new_v4().to_string();
        let num_connections = connections.unwrap_or(16).clamp(1, 32);

        let segments = if probe.accepts_ranges && probe.file_size > 0 {
            DownloadTask::create_segments(probe.file_size, num_connections)
        } else {
            vec![crate::model::Segment::new(0, 0, if probe.file_size > 0 { probe.file_size - 1 } else { 0 })]
        };

        let task = DownloadTask {
            id: task_id.clone(),
            url: download_url,
            output_path: output_path.to_string_lossy().to_string(),
            filename: filename.clone(),
            file_size: probe.file_size,
            downloaded_bytes: 0,
            status: if auto_start { DownloadStatus::DOWNLOADING } else { DownloadStatus::PAUSED },
            connections: num_connections,
            max_speed_bps: 0.0,
            speed_bps: 0.0,
            eta_seconds: 0.0,
            category,
            created_at: chrono::Utc::now().timestamp() as f64,
            completed_at: None,
            error_message: None,
            segments,
        };

        task.save_state();
        qm.tasks.insert(task_id.clone(), task.clone());
        qm.save_to_disk();

        if auto_start {
            drop(qm);
            Self::start_download(qm_arc, &task_id).await?;
        }

        Ok(task)
    }

    pub async fn start_download(qm_arc: Arc<RwLock<Self>>, task_id: &str) -> anyhow::Result<()> {
        let (task, client, progress_tx, limiter) = {
            let mut qm = qm_arc.write().await;
            let task = match qm.tasks.get_mut(task_id) {
                Some(t) => {
                    t.status = DownloadStatus::DOWNLOADING;
                    t.clone()
                }
                None => return Err(anyhow::anyhow!("Task not found")),
            };
            (task, qm.client.clone(), qm.progress_tx.clone(), qm.speed_limiter.clone())
        };

        if task.url.starts_with("magnet:") {
            let (stop_tx, stop_rx) = watch::channel(false);
            {
                let mut qm = qm_arc.write().await;
                qm.downloaders.insert(task_id.to_string(), stop_tx);
                qm.save_to_disk();
            }
            let task_clone = task.clone();
            let qm_clone = qm_arc.clone();
            tokio::spawn(async move {
                crate::torrent::start_torrent_task(task_clone, qm_clone, stop_rx).await;
            });
            return Ok(());
        }

        let (downloader, stop_tx) = SegmentDownloader::new(task, client, limiter);

        {
            let mut qm = qm_arc.write().await;
            qm.downloaders.insert(task_id.to_string(), stop_tx);
            qm.save_to_disk();
        }

        let qm_clone = qm_arc.clone();
        let id_str = task_id.to_string();
        tokio::spawn(async move {
            let res = downloader.run(progress_tx).await;
            let mut qm = qm_clone.write().await;
            qm.downloaders.remove(&id_str);
            if let Err(e) = res {
                if let Some(t) = qm.tasks.get_mut(&id_str) {
                    if t.status != DownloadStatus::PAUSED {
                        t.status = DownloadStatus::FAILED;
                        t.error_message = Some(e.to_string());
                    }
                }
            }
            qm.save_to_disk();
        });

        Ok(())
    }

    pub async fn pause_task(&mut self, task_id: &str) -> bool {
        crate::logger::log_event("INFO", "QUEUE", &format!("Pausing task {}", task_id));
        if let Some(stop_tx) = self.downloaders.remove(task_id) {
            let _ = stop_tx.send(true);
        }
        if let Some(t) = self.tasks.get_mut(task_id) {
            t.status = DownloadStatus::PAUSED;
            t.speed_bps = 0.0;
            t.save_state();
            self.save_to_disk();
            return true;
        }
        false
    }

    pub async fn resume_task(qm_arc: Arc<RwLock<Self>>, task_id: &str) -> bool {
        crate::logger::log_event("INFO", "QUEUE", &format!("Resuming task {}", task_id));
        {
            let mut qm = qm_arc.write().await;
            qm.cancelled_ids.remove(task_id);
        }
        Self::start_download(qm_arc, task_id).await.is_ok()
    }

    pub async fn cancel_task(&mut self, task_id: &str, remove_files: bool) -> bool {
        crate::logger::log_event("INFO", "QUEUE", &format!("Cancelling task {} (remove_files={})", task_id, remove_files));
        self.cancelled_ids.insert(task_id.to_string());
        self.pause_task(task_id).await;
        if let Some(task) = self.tasks.remove(task_id) {
            let output_path = task.output_path.clone();
            let state_path = task.state_path().to_path_buf();
            self.save_to_disk();

            if remove_files {
                tokio::spawn(async move {
                    for _ in 0..10 {
                        let p = std::path::Path::new(&output_path);
                        if !p.exists() {
                            break;
                        }
                        if p.is_dir() {
                            if std::fs::remove_dir_all(p).is_ok() {
                                crate::logger::log_event("INFO", "QUEUE", &format!("Deleted local folder: {}", output_path));
                                break;
                            }
                        } else {
                            if std::fs::remove_file(p).is_ok() {
                                crate::logger::log_event("INFO", "QUEUE", &format!("Deleted local file: {}", output_path));
                                break;
                            }
                        }
                        tokio::time::sleep(tokio::time::Duration::from_millis(80)).await;
                    }
                    let _ = std::fs::remove_file(&state_path);
                    let part_file = format!("{}.part", output_path);
                    let _ = std::fs::remove_file(&part_file);
                });
            } else {
                let _ = std::fs::remove_file(state_path);
            }
            return true;
        }
        false
    }

    pub fn set_speed_limit(&mut self, limit_bps: f64) {
        self.global_speed_limit_bps = limit_bps;
        self.speed_limiter.set_limit(limit_bps as u64);
    }
}

fn dirs_next_download_dir() -> Option<PathBuf> {
    if let Ok(user) = std::env::var("USERPROFILE") {
        let p = PathBuf::from(user).join("Downloads");
        if p.exists() {
            return Some(p);
        }
    }
    None
}
