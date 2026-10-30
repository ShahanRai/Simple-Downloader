use std::io::Read;
use std::sync::Arc;
use tiny_http::{Header, Response, Server, StatusCode};
use tokio::sync::mpsc;

use internet_downloader_lib::engine::{probe_url, SegmentDownloader};
use internet_downloader_lib::model::{DownloadStatus, DownloadTask};

#[tokio::test]
async fn test_multi_connection_range_download() {
    let test_port = 29876;
    let server_addr = format!("127.0.0.1:{}", test_port);
    let server = Server::http(&server_addr).expect("Failed to start mock test server");

    // 4 MB test payload
    let payload_size: usize = 4 * 1024 * 1024;
    let mut original_data = vec![0u8; payload_size];
    for (i, byte) in original_data.iter_mut().enumerate() {
        *byte = ((i * 31 + 17) % 256) as u8;
    }
    let original_data_arc = Arc::new(original_data);

    // Mock HTTP Range Server thread
    let data_server = original_data_arc.clone();
    std::thread::spawn(move || {
        for request in server.incoming_requests() {
            let method = request.method().clone();
            let headers = request.headers().to_vec();

            if method == tiny_http::Method::Head {
                let mut resp = Response::empty(200);
                resp.add_header(Header::from_bytes(&b"Content-Length"[..], format!("{}", data_server.len()).as_bytes()).unwrap());
                resp.add_header(Header::from_bytes(&b"Accept-Ranges"[..], &b"bytes"[..]).unwrap());
                resp.add_header(Header::from_bytes(&b"Content-Disposition"[..], &b"attachment; filename=\"test_file.bin\""[..]).unwrap());
                let _ = request.respond(resp);
                continue;
            }

            // Check for Range header
            let mut range_header = None;
            for h in &headers {
                if h.field.as_str().as_str().eq_ignore_ascii_case("Range") {
                    range_header = Some(h.value.as_str().to_string());
                    break;
                }
            }

            if let Some(range_val) = range_header {
                if let Some(bytes_part) = range_val.strip_prefix("bytes=") {
                    let parts: Vec<&str> = bytes_part.split('-').collect();
                    let start: usize = parts[0].parse().unwrap_or(0);
                    let end: usize = if parts.len() > 1 && !parts[1].is_empty() {
                        parts[1].parse().unwrap_or(data_server.len() - 1)
                    } else {
                        data_server.len() - 1
                    };
                    let end = end.min(data_server.len() - 1);
                    let slice = &data_server[start..=end];

                    let mut resp = Response::from_data(slice).with_status_code(StatusCode(206));
                    resp.add_header(Header::from_bytes(&b"Content-Range"[..], format!("bytes {}-{}/{}", start, end, data_server.len()).as_bytes()).unwrap());
                    resp.add_header(Header::from_bytes(&b"Content-Length"[..], format!("{}", slice.len()).as_bytes()).unwrap());
                    resp.add_header(Header::from_bytes(&b"Accept-Ranges"[..], &b"bytes"[..]).unwrap());
                    let _ = request.respond(resp);
                    continue;
                }
            }

            let mut resp = Response::from_data(&data_server[..]);
            resp.add_header(Header::from_bytes(&b"Content-Length"[..], format!("{}", data_server.len()).as_bytes()).unwrap());
            resp.add_header(Header::from_bytes(&b"Accept-Ranges"[..], &b"bytes"[..]).unwrap());
            let _ = request.respond(resp);
        }
    });

    let client = reqwest::Client::new();
    let test_url = format!("http://{}/test_file.bin", server_addr);

    // 1. Test probe_url
    let probe = probe_url(&client, &test_url).await.expect("Probe failed");
    assert_eq!(probe.filename, "test_file.bin");
    assert_eq!(probe.file_size, payload_size as u64);
    assert!(probe.accepts_ranges);

    // 2. Test 4-stream SegmentDownloader
    let temp_dir = std::env::temp_dir().join("idm_rust_test");
    let _ = std::fs::create_dir_all(&temp_dir);
    let output_file = temp_dir.join("downloaded_test.bin");
    if output_file.exists() {
        let _ = std::fs::remove_file(&output_file);
    }

    let task = DownloadTask {
        id: "test-task-1".to_string(),
        url: test_url.clone(),
        output_path: output_file.to_string_lossy().to_string(),
        filename: "test_file.bin".to_string(),
        file_size: payload_size as u64,
        downloaded_bytes: 0,
        status: DownloadStatus::DOWNLOADING,
        connections: 4,
        max_speed_bps: 0.0,
        speed_bps: 0.0,
        eta_seconds: 0.0,
        category: "General".to_string(),
        created_at: 0.0,
        completed_at: None,
        error_message: None,
        segments: Vec::new(),
    };

    let (downloader, _stop_tx) = SegmentDownloader::new(task, client);
    let (progress_tx, mut progress_rx) = mpsc::channel(64);

    tokio::spawn(async move {
        while let Some(_task) = progress_rx.recv().await {}
    });

    downloader.run(progress_tx).await.expect("Downloader run failed");

    // 3. Verify downloaded file bytes & integrity
    assert!(output_file.exists());
    let mut downloaded_bytes = Vec::new();
    let mut file = std::fs::File::open(&output_file).expect("Open downloaded file failed");
    file.read_to_end(&mut downloaded_bytes).expect("Read failed");

    assert_eq!(downloaded_bytes.len(), payload_size);
    assert_eq!(downloaded_bytes, *original_data_arc);

    // Cleanup
    let _ = std::fs::remove_file(&output_file);
    let _ = std::fs::remove_file(format!("{}.state.json", output_file.to_string_lossy()));
    let _ = std::fs::remove_dir(&temp_dir);
}
