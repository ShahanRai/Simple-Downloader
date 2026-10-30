use std::collections::VecDeque;
use std::sync::{LazyLock, Mutex};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogEntry {
    pub id: u64,
    pub timestamp: String,
    pub level: String,
    pub target: String,
    pub message: String,
}

static LOG_ID_COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
static LOG_BUFFER: LazyLock<Mutex<VecDeque<LogEntry>>> = LazyLock::new(|| {
    Mutex::new(VecDeque::with_capacity(1000))
});

/// Records a system, engine, or torrent log entry
pub fn log_event(level: &str, target: &str, message: &str) {
    let now = chrono::Local::now();
    let timestamp = now.format("%Y-%m-%d %H:%M:%S%.3f").to_string();
    let id = LOG_ID_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);

    let entry = LogEntry {
        id,
        timestamp,
        level: level.to_uppercase(),
        target: target.to_string(),
        message: message.to_string(),
    };

    println!("[{}][{}][{}] {}", entry.timestamp, entry.level, entry.target, entry.message);

    if let Ok(mut buffer) = LOG_BUFFER.lock() {
        if buffer.len() >= 1000 {
            buffer.pop_front();
        }
        buffer.push_back(entry);
    }
}

pub fn get_all_logs() -> Vec<LogEntry> {
    if let Ok(buffer) = LOG_BUFFER.lock() {
        buffer.iter().cloned().collect()
    } else {
        Vec::new()
    }
}

pub fn clear_all_logs() {
    if let Ok(mut buffer) = LOG_BUFFER.lock() {
        buffer.clear();
    }
}

pub fn get_diagnostic_report(os_info: &str, tasks_summary: &str) -> String {
    let logs = get_all_logs();
    let mut out = String::new();
    out.push_str("=====================================================\n");
    out.push_str("        SIMPLE DOWNLOADER DIAGNOSTIC REPORT          \n");
    out.push_str("=====================================================\n");
    out.push_str(&format!("Generated: {}\n", chrono::Local::now().to_rfc3339()));
    out.push_str(&format!("Platform:  {}\n", os_info));
    out.push_str(&format!("Tasks:     {}\n\n", tasks_summary));
    out.push_str("--- DETAILED LOGS ---\n");

    if logs.is_empty() {
        out.push_str("(No log entries recorded yet)\n");
    } else {
        for entry in logs {
            out.push_str(&format!(
                "[{}] [{:5}] [{}] {}\n",
                entry.timestamp, entry.level, entry.target, entry.message
            ));
        }
    }
    out.push_str("=====================================================\n");
    out
}
