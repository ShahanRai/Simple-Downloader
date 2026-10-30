use std::sync::Arc;
use tiny_http::{Header, Method, Response, Server};
use tokio::sync::RwLock;

use crate::queue::QueueManager;

pub const DEFAULT_SERVER_PORT: u16 = 9653;

pub fn start_local_api_server(qm_arc: Arc<RwLock<QueueManager>>) {
    std::thread::spawn(move || {
        let addr = format!("127.0.0.1:{}", DEFAULT_SERVER_PORT);
        let server = match Server::http(&addr) {
            Ok(s) => s,
            Err(e) => {
                log::warn!("Could not bind local API server on {}: {}", addr, e);
                return;
            }
        };

        log::info!("⚡ Local HTTP API Bridge listening on http://{}", addr);

        for mut request in server.incoming_requests() {
            let url_str = request.url().to_string();
            let method = request.method().clone();

            let cors_origin = Header::from_bytes(&b"Access-Control-Allow-Origin"[..], &b"*"[..]).unwrap();
            let cors_methods = Header::from_bytes(&b"Access-Control-Allow-Methods"[..], &b"GET, POST, OPTIONS, PUT, DELETE"[..]).unwrap();
            let cors_headers = Header::from_bytes(&b"Access-Control-Allow-Headers"[..], &b"Content-Type, Authorization, X-Requested-With"[..]).unwrap();
            let content_type = Header::from_bytes(&b"Content-Type"[..], &b"application/json; charset=utf-8"[..]).unwrap();

            if method == Method::Options {
                let mut resp = Response::empty(204);
                resp.add_header(cors_origin);
                resp.add_header(cors_methods);
                resp.add_header(cors_headers);
                let _ = request.respond(resp);
                continue;
            }

            let path = url_str.split('?').next().unwrap_or("/").trim_end_matches('/');

            if method == Method::Get && (path == "" || path == "/ping" || path == "/status") {
                let qm = tauri::async_runtime::block_on(async { qm_arc.read().await.get_all_tasks() });
                let active = qm.iter().filter(|t| t.status == crate::model::DownloadStatus::DOWNLOADING).count();
                let speed: f64 = qm.iter().filter(|t| t.status == crate::model::DownloadStatus::DOWNLOADING).map(|t| t.speed_bps).sum();

                let json = serde_json::json!({
                    "app": "Internet Downloader",
                    "engine": "Rust Core",
                    "version": "2.0.0",
                    "status": "online",
                    "active_tasks": active,
                    "total_tasks": qm.len(),
                    "speed_bps": speed
                });

                let mut resp = Response::from_string(json.to_string());
                resp.add_header(cors_origin);
                resp.add_header(content_type);
                let _ = request.respond(resp);
            } else if method == Method::Get && path == "/tasks" {
                let tasks = tauri::async_runtime::block_on(async { qm_arc.read().await.get_all_tasks() });
                let json = serde_json::json!({ "tasks": tasks });
                let mut resp = Response::from_string(json.to_string());
                resp.add_header(cors_origin);
                resp.add_header(content_type);
                let _ = request.respond(resp);
            } else if method == Method::Post && path == "/resolve_youtube" {
                let mut body = String::new();
                let _ = request.as_reader().read_to_string(&mut body);

                #[derive(serde::Deserialize)]
                struct ResolvePayload {
                    url: Option<String>,
                }

                let payload: ResolvePayload = serde_json::from_str(&body).unwrap_or(ResolvePayload { url: None });

                if let Some(target_url) = payload.url {
                    match crate::youtube::resolve_youtube(&target_url) {
                        Ok(result) => {
                            let json = serde_json::json!({
                                "status": "success",
                                "title": result.title,
                                "formats": result.formats
                            });
                            let mut resp = Response::from_string(json.to_string());
                            resp.add_header(cors_origin);
                            resp.add_header(content_type);
                            let _ = request.respond(resp);
                        }
                        Err(e) => {
                            let json = serde_json::json!({ "status": "error", "error": e.to_string() });
                            let mut resp = Response::from_string(json.to_string()).with_status_code(500);
                            resp.add_header(cors_origin);
                            resp.add_header(content_type);
                            let _ = request.respond(resp);
                        }
                    }
                } else {
                    let json = serde_json::json!({ "status": "error", "error": "Missing URL" });
                    let mut resp = Response::from_string(json.to_string()).with_status_code(400);
                    resp.add_header(cors_origin);
                    resp.add_header(content_type);
                    let _ = request.respond(resp);
                }
            } else if method == Method::Post && path == "/download" {
                let mut body = String::new();
                let _ = request.as_reader().read_to_string(&mut body);

                #[derive(serde::Deserialize)]
                struct DownloadPayload {
                    url: Option<String>,
                    filename: Option<String>,
                    connections: Option<usize>,
                    auto_start: Option<bool>,
                }

                let payload: DownloadPayload = serde_json::from_str(&body).unwrap_or(DownloadPayload {
                    url: None,
                    filename: None,
                    connections: None,
                    auto_start: None,
                });

                if let Some(target_url) = payload.url {
                    let qm_clone = qm_arc.clone();
                    let conns = payload.connections.or(Some(16));
                    let auto = payload.auto_start.unwrap_or(true);
                    let custom_name = payload.filename;

                    let res = tauri::async_runtime::block_on(async move {
                        QueueManager::add_task(qm_clone, target_url, conns, auto, custom_name).await
                    });

                    match res {
                        Ok(task) => {
                            let json = serde_json::json!({
                                "status": "success",
                                "task_id": task.id,
                                "filename": task.filename,
                                "file_size": task.file_size
                            });
                            let mut resp = Response::from_string(json.to_string());
                            resp.add_header(cors_origin);
                            resp.add_header(content_type);
                            let _ = request.respond(resp);
                        }
                        Err(e) => {
                            let json = serde_json::json!({ "error": e.to_string() });
                            let mut resp = Response::from_string(json.to_string()).with_status_code(500);
                            resp.add_header(cors_origin);
                            resp.add_header(content_type);
                            let _ = request.respond(resp);
                        }
                    }
                } else {
                    let json = serde_json::json!({ "error": "Missing URL" });
                    let mut resp = Response::from_string(json.to_string()).with_status_code(400);
                    resp.add_header(cors_origin);
                    resp.add_header(content_type);
                    let _ = request.respond(resp);
                }
            } else if method == Method::Post && path.starts_with("/task/") {
                let parts: Vec<&str> = path.split('/').collect();
                if parts.len() >= 4 {
                    let task_id = parts[2];
                    let action = parts[3];

                    let qm_clone = qm_arc.clone();
                    let id_str = task_id.to_string();

                    tauri::async_runtime::block_on(async move {
                        let mut qm = qm_clone.write().await;
                        if action == "pause" {
                            qm.pause_task(&id_str).await;
                        } else if action == "resume" {
                            drop(qm);
                            QueueManager::resume_task(qm_clone.clone(), &id_str).await;
                        } else if action == "cancel" {
                            qm.cancel_task(&id_str, false).await;
                        }
                    });

                    let json = serde_json::json!({ "status": "ok" });
                    let mut resp = Response::from_string(json.to_string());
                    resp.add_header(cors_origin);
                    resp.add_header(content_type);
                    let _ = request.respond(resp);
                } else {
                    let mut resp = Response::empty(400);
                    resp.add_header(cors_origin);
                    let _ = request.respond(resp);
                }
            } else {
                let json = serde_json::json!({ "error": "Not Found" });
                let mut resp = Response::from_string(json.to_string()).with_status_code(404);
                resp.add_header(cors_origin);
                resp.add_header(content_type);
                let _ = request.respond(resp);
            }
        }
    });
}

