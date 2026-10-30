use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpStream, UdpSocket};
use tokio::sync::{watch, RwLock};

use crate::logger::log_event;
use crate::model::{DownloadStatus, DownloadTask, ProbeResult, Segment};
use crate::queue::QueueManager;

#[derive(Debug, Clone)]
pub struct MagnetInfo {
    pub info_hash_hex: String,
    pub info_hash_bytes: [u8; 20],
    pub display_name: String,
    pub trackers: Vec<String>,
    pub web_seeds: Vec<String>,
    pub exact_length: Option<u64>,
}

/// Parses a magnet:? URL into MagnetInfo metadata
pub fn parse_magnet(uri: &str) -> Option<MagnetInfo> {
    if !uri.starts_with("magnet:?") {
        return None;
    }

    let query = &uri[8..];
    let mut info_hash_bytes = [0u8; 20];
    let mut info_hash_hex = String::new();
    let mut display_name = String::new();
    let mut trackers = Vec::new();
    let mut web_seeds = Vec::new();
    let mut exact_length = None;

    for param in query.split('&') {
        if let Some((key, val)) = param.split_once('=') {
            let decoded_val = url_decode(val);
            match key {
                "xt" => {
                    if let Some(hash_str) = decoded_val.strip_prefix("urn:btih:") {
                        let clean_hash = hash_str.trim();
                        if clean_hash.len() == 40 {
                            if let Some(bytes) = hex_decode_20(clean_hash) {
                                info_hash_bytes = bytes;
                                info_hash_hex = clean_hash.to_lowercase();
                            }
                        } else if clean_hash.len() == 32 {
                            if let Some(bytes) = decode_base32_20(clean_hash) {
                                info_hash_bytes = bytes;
                                info_hash_hex = hex_encode(&bytes);
                            }
                        }
                    }
                }
                "dn" => {
                    if !decoded_val.is_empty() {
                        display_name = decoded_val;
                    }
                }
                "tr" => {
                    if !decoded_val.is_empty() && !trackers.contains(&decoded_val) {
                        trackers.push(decoded_val);
                    }
                }
                "ws" => {
                    if !decoded_val.is_empty() && !web_seeds.contains(&decoded_val) {
                        web_seeds.push(decoded_val);
                    }
                }
                "xl" => {
                    if let Ok(len) = decoded_val.parse::<u64>() {
                        exact_length = Some(len);
                    }
                }
                _ => {}
            }
        }
    }

    if info_hash_hex.is_empty() {
        return None;
    }

    // Add high-tier public UDP trackers for robust swarm discovery
    let default_trackers = [
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.stealth.si:80/announce",
        "udp://tracker.torrent.eu.org:451/announce",
        "udp://explodie.org:6969/announce",
        "udp://tracker.bittor.pw:1337/announce",
        "udp://tracker.openbittorrent.com:6969/announce",
        "http://tracker.opentrackr.org:1337/announce",
    ];
    for dt in &default_trackers {
        let s = dt.to_string();
        if !trackers.contains(&s) {
            trackers.push(s);
        }
    }

    if display_name.is_empty() {
        display_name = format!("Torrent_{}", &info_hash_hex[..8]);
    }

    Some(MagnetInfo {
        info_hash_hex,
        info_hash_bytes,
        display_name,
        trackers,
        web_seeds,
        exact_length,
    })
}

pub fn probe_magnet(uri: &str) -> ProbeResult {
    if let Some(mag) = parse_magnet(uri) {
        let filename = mag.display_name.clone();
        ProbeResult {
            url: uri.to_string(),
            filename: crate::model::sanitize_filename(&filename),
            file_size: mag.exact_length.unwrap_or(0),
            accepts_ranges: true,
            etag: None,
            content_type: Some("application/octet-stream".to_string()),
        }
    } else {
        ProbeResult {
            url: uri.to_string(),
            filename: "Magnet_Download".to_string(),
            file_size: 0,
            accepts_ranges: false,
            etag: None,
            content_type: Some("application/octet-stream".to_string()),
        }
    }
}

/// Zero-dependency Bencode parser
#[derive(Debug, Clone)]
pub enum BValue {
    Int(i64),
    Bytes(Vec<u8>),
    List(Vec<BValue>),
    Dict(Vec<(Vec<u8>, BValue)>),
}

impl BValue {
    pub fn parse(input: &[u8]) -> Option<(BValue, usize)> {
        if input.is_empty() {
            return None;
        }
        match input[0] {
            b'i' => {
                let end = input[1..].iter().position(|&b| b == b'e')? + 1;
                let s = std::str::from_utf8(&input[1..end]).ok()?;
                let val: i64 = s.parse().ok()?;
                Some((BValue::Int(val), end + 1))
            }
            b'l' => {
                let mut idx = 1;
                let mut list = Vec::new();
                while idx < input.len() && input[idx] != b'e' {
                    let (item, consumed) = BValue::parse(&input[idx..])?;
                    list.push(item);
                    idx += consumed;
                }
                if idx < input.len() && input[idx] == b'e' {
                    Some((BValue::List(list), idx + 1))
                } else {
                    None
                }
            }
            b'd' => {
                let mut idx = 1;
                let mut dict = Vec::new();
                while idx < input.len() && input[idx] != b'e' {
                    let (key_val, k_consumed) = BValue::parse(&input[idx..])?;
                    let key = match key_val {
                        BValue::Bytes(b) => b,
                        _ => return None,
                    };
                    idx += k_consumed;
                    let (val, v_consumed) = BValue::parse(&input[idx..])?;
                    dict.push((key, val));
                    idx += v_consumed;
                }
                if idx < input.len() && input[idx] == b'e' {
                    Some((BValue::Dict(dict), idx + 1))
                } else {
                    None
                }
            }
            b'0'..=b'9' => {
                let colon = input.iter().position(|&b| b == b':')?;
                let len_str = std::str::from_utf8(&input[..colon]).ok()?;
                let len: usize = len_str.parse().ok()?;
                let start = colon + 1;
                let end = start + len;
                if end > input.len() {
                    return None;
                }
                let bytes = input[start..end].to_vec();
                Some((BValue::Bytes(bytes), end))
            }
            _ => None,
        }
    }

    pub fn dict_get(&self, key: &str) -> Option<&BValue> {
        if let BValue::Dict(entries) = self {
            let key_bytes = key.as_bytes();
            for (k, v) in entries {
                if k.as_slice() == key_bytes {
                    return Some(v);
                }
            }
        }
        None
    }

    pub fn as_int(&self) -> Option<i64> {
        if let BValue::Int(v) = self {
            Some(*v)
        } else {
            None
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        if let BValue::Bytes(b) = self {
            std::str::from_utf8(b).ok()
        } else {
            None
        }
    }

    pub fn as_list(&self) -> Option<&[BValue]> {
        if let BValue::List(l) = self {
            Some(l.as_slice())
        } else {
            None
        }
    }
}

/// Executes an in-app download for a magnet: link
pub async fn start_torrent_task(
    task: DownloadTask,
    qm_arc: Arc<RwLock<QueueManager>>,
    stop_rx: watch::Receiver<bool>,
) {
    let task_id = task.id.clone();
    log_event("INFO", "TORRENT", &format!("Starting torrent task {}: {}", task_id, task.filename));

    let (client, speed_limiter) = {
        let qm = qm_arc.read().await;
        (qm.client.clone(), qm.speed_limiter.clone())
    };
    let output_path = PathBuf::from(&task.output_path);

    // 1. Parse Magnet URI
    let mag = match parse_magnet(&task.url) {
        Some(m) => m,
        None => {
            log_event("ERROR", "TORRENT", &format!("Task {}: Invalid or unsupported magnet URI format", task_id));
            let mut qm = qm_arc.write().await;
            if let Some(t) = qm.tasks.get_mut(&task_id) {
                t.status = DownloadStatus::FAILED;
                t.error_message = Some("Invalid or unsupported magnet URI format".to_string());
            }
            qm.save_to_disk();
            return;
        }
    };

    log_event("INFO", "TORRENT", &format!("Parsed magnet: hash={}, display_name='{}', trackers={}", mag.info_hash_hex, mag.display_name, mag.trackers.len()));

    if *stop_rx.borrow() {
        return;
    }

    // 2. Direct Web Seed stream if specified in magnet
    if let Some(first_ws) = mag.web_seeds.first() {
        let ws_url = first_ws.clone();
        log_event("INFO", "TORRENT", &format!("Checking direct web seed: {}", ws_url));
        if let Ok(mut resp) = client.get(&ws_url).send().await {
            if resp.status().is_success() {
                let total_size = resp.content_length().unwrap_or(0);
                if total_size > 0 {
                    let mut qm = qm_arc.write().await;
                    if let Some(t) = qm.tasks.get_mut(&task_id) {
                        t.file_size = total_size;
                    }
                    qm.save_to_disk();
                }

                if let Some(parent) = output_path.parent() {
                    let _ = std::fs::create_dir_all(parent);
                }

                if let Ok(mut file) = OpenOptions::new().create(true).write(true).open(&output_path) {
                    let mut downloaded: u64 = 0;
                    let mut last_tick = Instant::now();
                    let mut last_bytes = 0u64;

                    while let Ok(Some(chunk)) = resp.chunk().await {
                        if *stop_rx.borrow() {
                            let _ = file.flush();
                            return;
                        }
                        speed_limiter.acquire(chunk.len()).await;
                        let _ = file.write_all(&chunk);
                        downloaded += chunk.len() as u64;

                        if last_tick.elapsed().as_millis() >= 300 {
                            let speed = ((downloaded - last_bytes) as f64) / last_tick.elapsed().as_secs_f64();
                            last_tick = Instant::now();
                            last_bytes = downloaded;

                            let eta = if speed > 0.0 && total_size > downloaded {
                                (total_size - downloaded) as f64 / speed
                            } else {
                                0.0
                            };

                            let mut qm = qm_arc.write().await;
                            if qm.cancelled_ids.contains(&task_id) {
                                drop(file);
                                return;
                            }
                            if let Some(t) = qm.tasks.get_mut(&task_id) {
                                if t.status == DownloadStatus::PAUSED {
                                    drop(file);
                                    return;
                                }
                                t.downloaded_bytes = downloaded;
                                t.speed_bps = speed;
                                t.eta_seconds = eta;
                                t.status = DownloadStatus::DOWNLOADING;
                            }
                        }
                    }

                    let _ = file.flush();
                    drop(file);

                    let mut qm = qm_arc.write().await;
                    if let Some(t) = qm.tasks.get_mut(&task_id) {
                        t.downloaded_bytes = downloaded;
                        t.speed_bps = 0.0;
                        t.eta_seconds = 0.0;
                        t.status = DownloadStatus::COMPLETED;
                        t.completed_at = Some(chrono::Utc::now().timestamp() as f64);
                    }
                    qm.save_to_disk();
                    log_event("INFO", "TORRENT", &format!("Task {} completed successfully via web seed", task_id));
                    return;
                }
            }
        }
    }

    // 3. Retrieve metadata (.torrent) from public torrent metadata caches
    log_event("INFO", "TORRENT", &format!("Querying metadata caches for info_hash {}...", mag.info_hash_hex));
    let torrent_bytes = fetch_torrent_from_cache(&client, &mag.info_hash_hex).await;

    let mut actual_output_path = output_path.clone();
    if actual_output_path.to_string_lossy().to_lowercase().ends_with(".torrent") {
        let stem = actual_output_path.file_stem().unwrap_or_default().to_string_lossy();
        actual_output_path = actual_output_path.with_file_name(stem.to_string());
    }

    let mut web_seed_candidates = mag.web_seeds.clone();
    let mut detected_piece_len: u32 = 262144; // Default 256KB piece length
    let mut total_file_size: u64 = mag.exact_length.unwrap_or(0);

    if let Some(data) = torrent_bytes {
        log_event("INFO", "TORRENT", &format!("Successfully obtained .torrent metadata ({} bytes)", data.len()));
        if let Some((bval, _)) = BValue::parse(&data) {
            let mut inner_file_name = mag.display_name.clone();

            if let Some(info) = bval.dict_get("info") {
                if let Some(n) = info.dict_get("name").and_then(|v| v.as_str()) {
                    inner_file_name = n.to_string();
                }
                if let Some(plen) = info.dict_get("piece length").and_then(|v| v.as_int()) {
                    detected_piece_len = plen as u32;
                }
                if let Some(len) = info.dict_get("length").and_then(|v| v.as_int()) {
                    total_file_size = len as u64;
                } else if let Some(files) = info.dict_get("files").and_then(|v| v.as_list()) {
                    let mut total = 0u64;
                    for f in files {
                        if let Some(len) = f.dict_get("length").and_then(|v| v.as_int()) {
                            total += len as u64;
                        }
                    }
                    if total > 0 {
                        total_file_size = total;
                    }
                }
            }

            // Update filename and target path
            let sanitized_name = crate::model::sanitize_filename(&inner_file_name);
            actual_output_path = actual_output_path.with_file_name(&sanitized_name);

            {
                let mut qm = qm_arc.write().await;
                if let Some(t) = qm.tasks.get_mut(&task_id) {
                    t.filename = sanitized_name.clone();
                    t.file_size = total_file_size;
                    t.output_path = actual_output_path.to_string_lossy().to_string();
                }
                qm.save_to_disk();
            }

            log_event("INFO", "TORRENT", &format!("Parsed metadata: payload='{}', size={} bytes, piece_len={}", sanitized_name, total_file_size, detected_piece_len));

            // Extract url-list (web seeds)
            if let Some(url_list) = bval.dict_get("url-list") {
                if let Some(s) = url_list.as_str() {
                    let clean = if s.ends_with('/') {
                        format!("{}{}", s, inner_file_name)
                    } else {
                        s.to_string()
                    };
                    web_seed_candidates.push(clean);
                } else if let Some(list) = url_list.as_list() {
                    for item in list {
                        if let Some(s) = item.as_str() {
                            let clean = if s.ends_with('/') {
                                format!("{}{}", s, inner_file_name)
                            } else {
                                s.to_string()
                            };
                            web_seed_candidates.push(clean);
                        }
                    }
                }
            }
        }
    } else {
        log_event("WARN", "TORRENT", "Cache lookup yielded no cached .torrent file; proceeding to tracker peer swarm");
    }

    if *stop_rx.borrow() {
        return;
    }

    // 4. Test candidate web seeds if any found
    for ws_url in &web_seed_candidates {
        if *stop_rx.borrow() {
            return;
        }
        log_event("INFO", "TORRENT", &format!("Testing candidate web seed: {}", ws_url));
        if let Ok(mut resp) = client.get(ws_url).send().await {
            if resp.status().is_success() {
                let total_size = resp.content_length().unwrap_or(total_file_size);
                if let Some(parent) = actual_output_path.parent() {
                    let _ = std::fs::create_dir_all(parent);
                }

                if let Ok(mut file) = OpenOptions::new().create(true).write(true).open(&actual_output_path) {
                    let mut downloaded: u64 = 0;
                    let mut last_tick = Instant::now();
                    let mut last_bytes = 0u64;

                    while let Ok(Some(chunk)) = resp.chunk().await {
                        if *stop_rx.borrow() {
                            let _ = file.flush();
                            return;
                        }
                        speed_limiter.acquire(chunk.len()).await;
                        let _ = file.write_all(&chunk);
                        downloaded += chunk.len() as u64;

                        if last_tick.elapsed().as_millis() >= 250 {
                            let speed = ((downloaded - last_bytes) as f64) / last_tick.elapsed().as_secs_f64();
                            last_tick = Instant::now();
                            last_bytes = downloaded;

                            let eta = if speed > 0.0 && total_size > downloaded {
                                (total_size - downloaded) as f64 / speed
                            } else {
                                0.0
                            };

                            let mut qm = qm_arc.write().await;
                            if qm.cancelled_ids.contains(&task_id) {
                                drop(file);
                                return;
                            }
                            if let Some(t) = qm.tasks.get_mut(&task_id) {
                                if t.status == DownloadStatus::PAUSED {
                                    drop(file);
                                    return;
                                }
                                t.downloaded_bytes = downloaded;
                                if total_size > 0 {
                                    t.file_size = total_size;
                                }
                                t.speed_bps = speed;
                                t.eta_seconds = eta;
                                t.status = DownloadStatus::DOWNLOADING;
                            }
                        }
                    }

                    let _ = file.flush();
                    drop(file);

                    if downloaded > 0 && (total_size == 0 || downloaded >= total_size) {
                        let mut qm = qm_arc.write().await;
                        if let Some(t) = qm.tasks.get_mut(&task_id) {
                            t.downloaded_bytes = downloaded;
                            if total_size > 0 {
                                t.file_size = total_size;
                            }
                            t.speed_bps = 0.0;
                            t.eta_seconds = 0.0;
                            t.status = DownloadStatus::COMPLETED;
                            t.completed_at = Some(chrono::Utc::now().timestamp() as f64);
                        }
                        qm.save_to_disk();
                        log_event("INFO", "TORRENT", &format!("Task {} completed successfully via web seed {}", task_id, ws_url));
                        return;
                    }
                }
            }
        }
    }

    if *stop_rx.borrow() {
        return;
    }

    // 5. Query Trackers (UDP BEP 15 & HTTP BEP 03)
    log_event("INFO", "TORRENT", &format!("Discovering swarm peers across {} trackers...", mag.trackers.len()));
    let peer_list = query_all_trackers(&client, &mag, total_file_size).await;
    log_event("INFO", "TORRENT", &format!("Swarm discovery complete: discovered {} total peers", peer_list.len()));

    if peer_list.is_empty() {
        log_event("WARN", "TORRENT", &format!("Task {}: No responsive peers found across trackers yet.", task_id));
        let mut qm = qm_arc.write().await;
        if let Some(t) = qm.tasks.get_mut(&task_id) {
            if t.status != DownloadStatus::PAUSED {
                t.error_message = Some("Searching for active BitTorrent peers in swarm...".to_string());
                t.status = DownloadStatus::DOWNLOADING;
            }
        }
        qm.save_to_disk();
    } else {
        let mut qm = qm_arc.write().await;
        if let Some(t) = qm.tasks.get_mut(&task_id) {
            t.status = DownloadStatus::DOWNLOADING;
            t.connections = peer_list.len().min(16);
            if t.file_size == 0 {
                t.file_size = total_file_size.max(10_000_000);
            }
            t.segments = (0..t.connections)
                .map(|i| Segment::new(i, i as u64 * 1000, (i + 1) as u64 * 1000))
                .collect();
        }
        qm.save_to_disk();
    }

    if let Some(parent) = actual_output_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    // 6. Connect to Swarm Peers and Stream Payload Pieces
    let mut downloaded_bytes_total: u64 = 0;
    let piece_length = detected_piece_len.max(16384);
    let block_size = 16384u32; // Standard 16KB BitTorrent block

    for peer_addr in peer_list.iter().take(12) {
        if *stop_rx.borrow() {
            log_event("INFO", "TORRENT", &format!("Task {} stopped by user", task_id));
            return;
        }

        {
            let qm = qm_arc.read().await;
            if qm.cancelled_ids.contains(&task_id) {
                return;
            }
        }

        log_event("INFO", "TORRENT", &format!("Connecting to peer {} for transfer...", peer_addr));
        let stream_res = tokio::time::timeout(Duration::from_secs(3), TcpStream::connect(peer_addr)).await;

        if let Ok(Ok(mut socket)) = stream_res {
            log_event("INFO", "TORRENT", &format!("Connected to peer {}. Sending BitTorrent handshake...", peer_addr));

            // Handshake message (68 bytes)
            let mut handshake = Vec::with_capacity(68);
            handshake.push(19u8);
            handshake.extend_from_slice(b"BitTorrent protocol");
            handshake.extend_from_slice(&[0u8; 8]);
            handshake.extend_from_slice(&mag.info_hash_bytes);
            handshake.extend_from_slice(b"-SD1000-012345678901");

            if socket.write_all(&handshake).await.is_err() {
                continue;
            }

            let mut resp_handshake = [0u8; 68];
            if tokio::time::timeout(Duration::from_secs(3), socket.read_exact(&mut resp_handshake)).await.is_err() {
                continue;
            }

            if &resp_handshake[1..20] != b"BitTorrent protocol" {
                continue;
            }

            log_event("INFO", "TORRENT", &format!("Handshake acknowledged by peer {}", peer_addr));

            // Send unchoke (1) & interested (2)
            let _ = socket.write_all(&[0, 0, 0, 1, 2]).await; // interested
            let _ = socket.write_all(&[0, 0, 0, 1, 1]).await; // unchoke

            let mut is_unchoked = false;
            let mut peer_read_buf = vec![0u8; 65536];

            // Open destination file with shared read/write access
            let file_opt = OpenOptions::new()
                .create(true)
                .read(true)
                .write(true)
                .open(&actual_output_path);

            if file_opt.is_err() {
                log_event("ERROR", "TORRENT", &format!("Failed to open destination file for payload: {}", actual_output_path.display()));
                break;
            }
            let mut file = file_opt.unwrap();

            let mut speed_calc_time = Instant::now();
            let mut speed_calc_bytes = downloaded_bytes_total;

            // Session read loop with peer
            let mut piece_idx = (downloaded_bytes_total / piece_length as u64) as u32;
            let mut consecutive_timeouts = 0u32;
            let max_timeouts = 8u32;

            loop {
                if *stop_rx.borrow() {
                    let _ = file.flush();
                    drop(file);
                    return;
                }

                {
                    let qm = qm_arc.read().await;
                    if qm.cancelled_ids.contains(&task_id) {
                        drop(file);
                        return;
                    }
                }

                // If unchoked, request next block
                if is_unchoked {
                    let byte_offset = piece_idx as u64 * piece_length as u64;
                    if total_file_size > 0 && byte_offset >= total_file_size {
                        // All pieces requested — wait for remaining data
                        break;
                    }
                    let mut req_msg = Vec::with_capacity(17);
                    req_msg.extend_from_slice(&13u32.to_be_bytes()); // length: 13
                    req_msg.push(6u8); // id: 6 (request)
                    req_msg.extend_from_slice(&piece_idx.to_be_bytes()); // index
                    req_msg.extend_from_slice(&0u32.to_be_bytes()); // begin
                    req_msg.extend_from_slice(&block_size.to_be_bytes()); // length
                    if socket.write_all(&req_msg).await.is_err() {
                        break;
                    }
                }

                // Read next message frame
                match tokio::time::timeout(Duration::from_millis(2000), socket.read(&mut peer_read_buf)).await {
                    Ok(Ok(n)) if n >= 4 => {
                        consecutive_timeouts = 0;
                        let mut cursor = 0;
                        while cursor + 4 <= n {
                            let msg_len = u32::from_be_bytes([
                                peer_read_buf[cursor],
                                peer_read_buf[cursor + 1],
                                peer_read_buf[cursor + 2],
                                peer_read_buf[cursor + 3],
                            ]) as usize;
                            cursor += 4;

                            if msg_len == 0 {
                                continue; // Keep-alive
                            }

                            if cursor < n {
                                let msg_id = peer_read_buf[cursor];
                                cursor += 1;

                                match msg_id {
                                    1 => {
                                        is_unchoked = true;
                                        log_event("INFO", "TORRENT", &format!("Peer {} sent UNCHOKE; requesting blocks...", peer_addr));
                                    }
                                    0 => {
                                        is_unchoked = false;
                                        log_event("INFO", "TORRENT", &format!("Peer {} sent CHOKE; pausing requests", peer_addr));
                                    }
                                    7 => {
                                        // Piece block payload: index(4) + begin(4) + block
                                        if cursor + 8 <= n {
                                            let p_idx = u32::from_be_bytes([
                                                peer_read_buf[cursor],
                                                peer_read_buf[cursor + 1],
                                                peer_read_buf[cursor + 2],
                                                peer_read_buf[cursor + 3],
                                            ]);
                                            let p_begin = u32::from_be_bytes([
                                                peer_read_buf[cursor + 4],
                                                peer_read_buf[cursor + 5],
                                                peer_read_buf[cursor + 6],
                                                peer_read_buf[cursor + 7],
                                            ]);
                                            cursor += 8;

                                            let block_len = (msg_len.saturating_sub(9)).min(n.saturating_sub(cursor));
                                            if block_len > 0 {
                                                let block_data = &peer_read_buf[cursor..cursor + block_len];
                                                cursor += block_len;

                                                speed_limiter.acquire(block_len).await;
                                                let file_offset = (p_idx as u64 * piece_length as u64) + p_begin as u64;
                                                let _ = file.seek(SeekFrom::Start(file_offset));
                                                let _ = file.write_all(block_data);

                                                downloaded_bytes_total += block_len as u64;
                                                piece_idx = piece_idx.max(p_idx + 1); // advance to next piece

                                                let elapsed = speed_calc_time.elapsed().as_secs_f64();
                                                if elapsed >= 0.4 {
                                                    let speed = (downloaded_bytes_total - speed_calc_bytes) as f64 / elapsed;
                                                    speed_calc_time = Instant::now();
                                                    speed_calc_bytes = downloaded_bytes_total;

                                                    let eta = if speed > 0.0 && total_file_size > downloaded_bytes_total {
                                                        (total_file_size - downloaded_bytes_total) as f64 / speed
                                                    } else {
                                                        0.0
                                                    };

                                                    let mut qm = qm_arc.write().await;
                                                    if let Some(t) = qm.tasks.get_mut(&task_id) {
                                                        t.downloaded_bytes = downloaded_bytes_total;
                                                        t.speed_bps = speed;
                                                        t.eta_seconds = eta;
                                                        t.status = DownloadStatus::DOWNLOADING;
                                                        t.error_message = None;
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    _ => {
                                        let skip = (msg_len.saturating_sub(1)).min(n.saturating_sub(cursor));
                                        cursor += skip;
                                    }
                                }
                            }
                        }
                    }
                    Ok(Ok(0)) | Ok(Err(_)) => {
                        // Peer closed connection
                        log_event("INFO", "TORRENT", &format!("Peer {} closed connection after {} bytes", peer_addr, downloaded_bytes_total));
                        break;
                    }
                    _ => {
                        consecutive_timeouts += 1;
                        if consecutive_timeouts >= max_timeouts {
                            log_event("WARN", "TORRENT", &format!("Peer {} timed out {} times; moving on", peer_addr, consecutive_timeouts));
                            break;
                        }
                    }
                }
            }

            let _ = file.flush();
            drop(file);
        }
    }

    if downloaded_bytes_total > 0 {
        let mut qm = qm_arc.write().await;
        if let Some(t) = qm.tasks.get_mut(&task_id) {
            t.downloaded_bytes = downloaded_bytes_total;
            if total_file_size > 0 && downloaded_bytes_total >= total_file_size {
                t.status = DownloadStatus::COMPLETED;
                t.completed_at = Some(chrono::Utc::now().timestamp() as f64);
            }
        }
        qm.save_to_disk();
        log_event("INFO", "TORRENT", &format!("Task {} transferred {} bytes from peers", task_id, downloaded_bytes_total));
    }
}

/// Discovers peers across all available UDP and HTTP trackers
async fn query_all_trackers(client: &reqwest::Client, mag: &MagnetInfo, file_size: u64) -> Vec<SocketAddr> {
    let mut all_peers = Vec::new();

    // Query UDP trackers concurrently
    for tr in &mag.trackers {
        if tr.starts_with("udp://") {
            if let Some(host_port) = tr.strip_prefix("udp://") {
                let clean_addr = host_port.split('/').next().unwrap_or(host_port);
                log_event("INFO", "TRACKER", &format!("Announcing via UDP to {}", clean_addr));
                if let Some(mut peers) = query_udp_tracker(clean_addr, &mag.info_hash_bytes, &mag.info_hash_bytes, file_size).await {
                    log_event("INFO", "TRACKER", &format!("UDP tracker {} returned {} peers", clean_addr, peers.len()));
                    all_peers.append(&mut peers);
                }
            }
        } else if tr.starts_with("http://") || tr.starts_with("https://") {
            log_event("INFO", "TRACKER", &format!("Announcing via HTTP to {}", tr));
            let mut peers = query_http_tracker(client, tr, mag).await;
            if !peers.is_empty() {
                log_event("INFO", "TRACKER", &format!("HTTP tracker {} returned {} peers", tr, peers.len()));
                all_peers.append(&mut peers);
            }
        }

        if all_peers.len() >= 48 {
            break;
        }
    }

    // Deduplicate peer addresses
    let mut unique = Vec::new();
    for p in all_peers {
        if !unique.contains(&p) {
            unique.push(p);
        }
    }
    unique
}

/// UDP Tracker Protocol (BEP 15) Announce
async fn query_udp_tracker(host_port: &str, info_hash: &[u8; 20], peer_id: &[u8; 20], file_size: u64) -> Option<Vec<SocketAddr>> {
    let socket = UdpSocket::bind("0.0.0.0:0").await.ok()?;
    let addrs: Vec<SocketAddr> = tokio::net::lookup_host(host_port).await.ok()?.collect();
    let tracker_addr = *addrs.first()?;

    // 1. Connection Request (16 bytes)
    // protocol_id: 0x41727101980 (8 bytes) | action: 0 (4 bytes) | transaction_id: 0x12345678 (4 bytes)
    let transaction_id = rand_u32();
    let mut conn_req = Vec::with_capacity(16);
    conn_req.extend_from_slice(&0x41727101980u64.to_be_bytes());
    conn_req.extend_from_slice(&0u32.to_be_bytes()); // connect
    conn_req.extend_from_slice(&transaction_id.to_be_bytes());

    socket.send_to(&conn_req, tracker_addr).await.ok()?;

    let mut buf = [0u8; 1024];
    let (n, _) = tokio::time::timeout(Duration::from_millis(1800), socket.recv_from(&mut buf)).await.ok()?.ok()?;
    if n < 16 {
        return None;
    }

    let action = u32::from_be_bytes([buf[0], buf[1], buf[2], buf[3]]);
    let resp_tx = u32::from_be_bytes([buf[4], buf[5], buf[6], buf[7]]);
    if action != 0 || resp_tx != transaction_id {
        return None;
    }

    let connection_id = u64::from_be_bytes([
        buf[8], buf[9], buf[10], buf[11], buf[12], buf[13], buf[14], buf[15],
    ]);

    // 2. Announce Request (98 bytes)
    let ann_tx = rand_u32();
    let mut ann_req = Vec::with_capacity(98);
    ann_req.extend_from_slice(&connection_id.to_be_bytes());
    ann_req.extend_from_slice(&1u32.to_be_bytes()); // action: announce
    ann_req.extend_from_slice(&ann_tx.to_be_bytes());
    ann_req.extend_from_slice(info_hash);
    ann_req.extend_from_slice(peer_id);
    ann_req.extend_from_slice(&0u64.to_be_bytes()); // downloaded
    ann_req.extend_from_slice(&file_size.to_be_bytes()); // left
    ann_req.extend_from_slice(&0u64.to_be_bytes()); // uploaded
    ann_req.extend_from_slice(&0u32.to_be_bytes()); // event: 0 (none)
    ann_req.extend_from_slice(&0u32.to_be_bytes()); // IP: 0
    ann_req.extend_from_slice(&rand_u32().to_be_bytes()); // key
    ann_req.extend_from_slice(&50i32.to_be_bytes()); // num_want: 50
    ann_req.extend_from_slice(&6881u16.to_be_bytes()); // port: 6881

    socket.send_to(&ann_req, tracker_addr).await.ok()?;

    let (n, _) = tokio::time::timeout(Duration::from_millis(2000), socket.recv_from(&mut buf)).await.ok()?.ok()?;
    if n < 20 {
        return None;
    }

    let action = u32::from_be_bytes([buf[0], buf[1], buf[2], buf[3]]);
    let resp_tx = u32::from_be_bytes([buf[4], buf[5], buf[6], buf[7]]);
    if action != 1 || resp_tx != ann_tx {
        return None;
    }

    let mut peers = Vec::new();
    let peer_bytes = &buf[20..n];
    for chunk in peer_bytes.chunks_exact(6) {
        let ip = std::net::Ipv4Addr::new(chunk[0], chunk[1], chunk[2], chunk[3]);
        let port = u16::from_be_bytes([chunk[4], chunk[5]]);
        if port > 0 {
            peers.push(SocketAddr::V4(std::net::SocketAddrV4::new(ip, port)));
        }
    }

    Some(peers)
}

/// HTTP Tracker Protocol (BEP 03) Announce
async fn query_http_tracker(client: &reqwest::Client, tr: &str, mag: &MagnetInfo) -> Vec<SocketAddr> {
    let mut peers = Vec::new();
    let peer_id = "-SD1000-012345678901";
    let encoded_hash = url_encode_bytes(&mag.info_hash_bytes);

    let sep = if tr.contains('?') { "&" } else { "?" };
    let announce_url = format!(
        "{}{}info_hash={}&peer_id={}&port=6881&uploaded=0&downloaded=0&left=1000&compact=1",
        tr, sep, encoded_hash, peer_id
    );

    if let Ok(resp) = client.get(&announce_url).timeout(Duration::from_secs(3)).send().await {
        if resp.status().is_success() {
            if let Ok(bytes) = resp.bytes().await {
                if let Some((bval, _)) = BValue::parse(&bytes) {
                    if let Some(peers_val) = bval.dict_get("peers") {
                        if let BValue::Bytes(p_bytes) = peers_val {
                            for chunk in p_bytes.chunks_exact(6) {
                                let ip = std::net::Ipv4Addr::new(chunk[0], chunk[1], chunk[2], chunk[3]);
                                let port = u16::from_be_bytes([chunk[4], chunk[5]]);
                                if port > 0 {
                                    peers.push(SocketAddr::V4(std::net::SocketAddrV4::new(ip, port)));
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    peers
}

/// Queries public HTTP BitTorrent caches for .torrent metadata
async fn fetch_torrent_from_cache(client: &reqwest::Client, hash_hex: &str) -> Option<Vec<u8>> {
    let hash_upper = hash_hex.to_uppercase();
    let hash_lower = hash_hex.to_lowercase();

    let urls = [
        format!("https://itorrents.org/torrent/{}.torrent", hash_upper),
        format!("https://itorrents.org/torrent/{}.torrent", hash_lower),
        format!("https://btcache.me/torrent/{}.torrent", hash_upper),
        format!("https://torrage.info/torrent.php?h={}", hash_upper),
    ];

    for u in &urls {
        if let Ok(resp) = client.get(u).header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)").timeout(Duration::from_secs(3)).send().await {
            if resp.status().is_success() {
                if let Ok(bytes) = resp.bytes().await {
                    if bytes.len() > 50 && bytes.starts_with(b"d") {
                        return Some(bytes.to_vec());
                    }
                }
            }
        }
    }
    None
}

// Helpers

fn rand_u32() -> u32 {
    let now = Instant::now().elapsed().as_nanos();
    (now as u32) ^ 0x5A5A5A5A
}

fn hex_decode_20(s: &str) -> Option<[u8; 20]> {
    if s.len() != 40 {
        return None;
    }
    let mut out = [0u8; 20];
    let bytes = s.as_bytes();
    for i in 0..20 {
        let h = hex_val(bytes[i * 2])?;
        let l = hex_val(bytes[i * 2 + 1])?;
        out[i] = (h << 4) | l;
    }
    Some(out)
}

fn hex_val(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        b'A'..=b'F' => Some(b - b'A' + 10),
        _ => None,
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        use std::fmt::Write;
        let _ = write!(s, "{:02x}", b);
    }
    s
}

fn decode_base32_20(s: &str) -> Option<[u8; 20]> {
    if s.len() != 32 {
        return None;
    }
    let mut bits = 0u64;
    let mut bit_count = 0;
    let mut out = [0u8; 20];
    let mut out_idx = 0;

    for &b in s.as_bytes() {
        let val = match b {
            b'A'..=b'Z' => b - b'A',
            b'a'..=b'z' => b - b'a',
            b'2'..=b'7' => b - b'2' + 26,
            _ => return None,
        } as u64;

        bits = (bits << 5) | val;
        bit_count += 5;

        while bit_count >= 8 {
            bit_count -= 8;
            if out_idx < 20 {
                out[out_idx] = ((bits >> bit_count) & 0xFF) as u8;
                out_idx += 1;
            }
        }
    }

    if out_idx == 20 {
        Some(out)
    } else {
        None
    }
}

fn url_decode(s: &str) -> String {
    let s_clean = s.replace('+', " ");
    url::form_urlencoded::parse(format!("v={}", s_clean).as_bytes())
        .next()
        .map(|(_, val)| val.into_owned())
        .unwrap_or(s_clean)
}

fn url_encode_bytes(bytes: &[u8]) -> String {
    let mut s = String::new();
    for &b in bytes {
        if b.is_ascii_alphanumeric() || b == b'-' || b == b'_' || b == b'.' || b == b'~' {
            s.push(b as char);
        } else {
            use std::fmt::Write;
            let _ = write!(s, "%{:02X}", b);
        }
    }
    s
}
