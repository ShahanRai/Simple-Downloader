use std::io::Write;
use std::path::PathBuf;
use std::time::Instant;
use tokio::sync::mpsc;

use crate::engine::{probe_url, SegmentDownloader};
use crate::model::{infer_category, DownloadStatus, DownloadTask};

pub async fn run_cli(args: Vec<String>) -> anyhow::Result<()> {
    let mut url: Option<String> = None;
    let mut connections: usize = 16;
    let mut output_path: Option<String> = None;
    let mut speed_limit_bps: f64 = 0.0;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "-c" | "--connections" => {
                if i + 1 < args.len() {
                    connections = args[i + 1].parse().unwrap_or(16).clamp(1, 32);
                    i += 1;
                }
            }
            "-o" | "--output" => {
                if i + 1 < args.len() {
                    output_path = Some(args[i + 1].clone());
                    i += 1;
                }
            }
            "-s" | "--speed-limit" => {
                if i + 1 < args.len() {
                    let kb: f64 = args[i + 1].parse().unwrap_or(0.0);
                    speed_limit_bps = kb * 1024.0;
                    i += 1;
                }
            }
            "-h" | "--help" => {
                print_cli_help();
                return Ok(());
            }
            other => {
                if other.starts_with("http://") || other.starts_with("https://") {
                    url = Some(other.to_string());
                }
            }
        }
        i += 1;
    }

    let target_url = match url {
        Some(u) => u,
        None => {
            print_cli_help();
            return Ok(());
        }
    };

    println!("\x1b[1;36m====================================================================\x1b[0m");
    println!("\x1b[1;36m  ⚡ INTERNET DOWNLOADER (Rust + Tauri Acceleration Core)\x1b[0m");
    println!("\x1b[1;36m====================================================================\x1b[0m");

    let client = reqwest::Client::builder()
        .pool_max_idle_per_host(32)
        .build()?;

    print!("[*] Probing remote server and headers... ");
    let _ = std::io::stdout().flush();
    let probe = probe_url(&client, &target_url).await?;
    println!("\x1b[1;32mDONE\x1b[0m");

    println!("    • Target: {}", target_url);
    println!("    • File:   {}", probe.filename);
    println!("    • Size:   {}", format_bytes(probe.file_size));
    println!("    • Ranges: {}", if probe.accepts_ranges { "✓ RFC 7233 Accelerated" } else { "Single Stream (No Ranges)" });
    println!("    • Conns:  {} Parallel Streams", connections);

    let downloads_dir = dirs_download_dir().unwrap_or_else(|| PathBuf::from("."));
    let final_output = if let Some(custom) = output_path {
        let p = PathBuf::from(custom);
        if p.is_dir() { p.join(&probe.filename) } else { p }
    } else {
        downloads_dir.join(&probe.filename)
    };

    println!("    • Output: {}", final_output.display());
    println!("\x1b[1;36m--------------------------------------------------------------------\x1b[0m");

    let task = DownloadTask {
        id: uuid::Uuid::new_v4().to_string(),
        url: target_url.clone(),
        output_path: final_output.to_string_lossy().to_string(),
        filename: probe.filename.clone(),
        file_size: probe.file_size,
        downloaded_bytes: 0,
        status: DownloadStatus::DOWNLOADING,
        connections,
        max_speed_bps: speed_limit_bps,
        speed_bps: 0.0,
        eta_seconds: 0.0,
        category: infer_category(&probe.filename).to_string(),
        created_at: chrono::Utc::now().timestamp() as f64,
        completed_at: None,
        error_message: None,
        segments: Vec::new(),
    };

    let limiter = crate::engine::SpeedLimiter::new(speed_limit_bps as u64);
    let (downloader, _stop_tx) = SegmentDownloader::new(task, client, limiter);
    let (progress_tx, mut progress_rx) = mpsc::channel::<DownloadTask>(64);

    let start_time = Instant::now();

    // Progress printer task
    let progress_handle = tokio::spawn(async move {
        let mut last_print = Instant::now();
        while let Some(current) = progress_rx.recv().await {
            if last_print.elapsed().as_millis() >= 200 || current.status == DownloadStatus::COMPLETED {
                last_print = Instant::now();
                let pct = current.progress_pct();
                let bar_width: usize = 32;
                let filled = ((pct / 100.0) * bar_width as f64).round() as usize;
                let empty = bar_width.saturating_sub(filled);
                let bar: String = "█".repeat(filled) + &"░".repeat(empty);

                let speed_str = format!("{}/s", format_bytes(current.speed_bps as u64));
                let eta_str = if current.eta_seconds > 0.0 {
                    format!("{:.0}s", current.eta_seconds)
                } else {
                    "—".to_string()
                };

                print!(
                    "\r\x1b[K\x1b[1;34m[{}]\x1b[0m \x1b[1;32m{:5.1}%\x1b[0m ({}/{}) | \x1b[1;36m{}\x1b[0m | ETA: {}",
                    bar,
                    pct,
                    format_bytes(current.downloaded_bytes),
                    format_bytes(current.file_size),
                    speed_str,
                    eta_str
                );
                let _ = std::io::stdout().flush();
            }
        }
    });

    downloader.run(progress_tx).await?;
    let _ = progress_handle.await;

    let elapsed = start_time.elapsed().as_secs_f64();
    let avg_speed = if elapsed > 0.0 { probe.file_size as f64 / elapsed } else { 0.0 };

    println!("\n\x1b[1;32m[✓ COMPLETED]\x1b[0m Finished in {:.2}s (Average: {}/s)", elapsed, format_bytes(avg_speed as u64));
    println!("Saved to: {}", final_output.display());

    Ok(())
}

fn print_cli_help() {
    println!("Internet Downloader (Rust Core CLI)");
    println!("Usage:");
    println!("  internet-downloader [URL] [OPTIONS]");
    println!();
    println!("Options:");
    println!("  -c, --connections <N>    Number of concurrent range streams (default: 16)");
    println!("  -o, --output <PATH>      Custom output filename or directory");
    println!("  -s, --speed-limit <KB>   Speed limit in KB/s (0 = unlimited)");
    println!("  -h, --help               Show this help message");
}

fn format_bytes(bytes: u64) -> String {
    if bytes == 0 { return "0 B".to_string(); }
    let units = ["B", "KB", "MB", "GB", "TB"];
    let mut b = bytes as f64;
    let mut i = 0;
    while b >= 1024.0 && i < units.len() - 1 {
        b /= 1024.0;
        i += 1;
    }
    format!("{:.1} {}", b, units[i])
}

fn dirs_download_dir() -> Option<PathBuf> {
    if let Ok(user) = std::env::var("USERPROFILE") {
        let p = PathBuf::from(user).join("Downloads");
        if p.exists() { return Some(p); }
    }
    None
}
