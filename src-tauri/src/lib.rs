pub mod cli;
pub mod commands;
pub mod engine;
pub mod model;
pub mod queue;
pub mod server;
pub mod clipboard;
pub mod youtube;
pub mod torrent;
pub mod logger;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Emitter, Manager};
use tokio::sync::{mpsc, RwLock};

use commands::AppState;
use queue::QueueManager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let minimize_to_tray = Arc::new(AtomicBool::new(false));
    let tray_close_flag = minimize_to_tray.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::default().build())
        .setup(move |app| {
            let handle = app.handle().clone();

            // Progress event channel
            let (progress_tx, mut progress_rx) = mpsc::channel::<model::DownloadTask>(128);

            // Initialize QueueManager
            let qm = QueueManager::new(progress_tx);
            let qm_arc = Arc::new(RwLock::new(qm));

            // Forward download progress to UI and sync QueueManager tasks
            let handle_clone = handle.clone();
            let qm_progress_sync = qm_arc.clone();
            tauri::async_runtime::spawn(async move {
                while let Some(task) = progress_rx.recv().await {
                    {
                        let qm_lock = qm_progress_sync.read().await;
                        if qm_lock.cancelled_ids.contains(&task.id) {
                            let _ = handle_clone.emit("download-progress", task);
                            continue;
                        }
                    }
                    if let Ok(mut qm_lock) = qm_progress_sync.try_write() {
                        qm_lock.tasks.insert(task.id.clone(), task.clone());
                    }
                    let _ = handle_clone.emit("download-progress", task);
                }
            });

            // Start Local API Bridge for browser extensions (127.0.0.1:9653)
            server::start_local_api_server(qm_arc.clone());

            // Start Windows Clipboard Monitor
            clipboard::start_clipboard_monitor(handle.clone());

            // Setup System Tray
            let show_i = MenuItem::with_id(app, "show", "Open Simple Downloader", true, None::<&str>)?;
            let quit_i = MenuItem::with_id(app, "quit", "Quit Simple Downloader", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&show_i, &quit_i])?;

            let default_icon = app.default_window_icon().cloned();
            let mut tray_builder = TrayIconBuilder::new()
                .menu(&tray_menu)
                .tooltip("Simple Downloader")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.unminimize();
                                let _ = window.set_focus();
                            }
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                let _ = window.show();
                                let _ = window.unminimize();
                                let _ = window.set_focus();
                            }
                        }
                    }
                });

            if let Some(icon) = default_icon {
                tray_builder = tray_builder.icon(icon);
            }

            let _tray = tray_builder.build(app)?;

            // Manage AppState
            app.manage(AppState {
                qm: qm_arc,
                minimize_to_tray: minimize_to_tray.clone(),
            });

            log::info!("⚡ Simple Downloader Rust Backend initialized successfully.");
            Ok(())
        })
        .on_window_event(move |window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if tray_close_flag.load(Ordering::Relaxed) {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_tasks,
            commands::probe_url,
            commands::add_download,
            commands::pause_task,
            commands::resume_task,
            commands::cancel_task,
            commands::set_speed_limit,
            commands::get_speed_limit,
            commands::open_file,
            commands::open_folder,
            commands::open_extension_dir,
            commands::get_default_download_dir,
            commands::select_save_directory,
            commands::minimize_window,
            commands::toggle_maximize_window,
            commands::close_window,
            commands::delete_tasks,
            commands::start_dragging,
            commands::resolve_youtube,
            commands::get_disk_free_space,
            commands::set_run_on_startup,
            commands::get_run_on_startup,
            commands::set_keep_pc_awake,
            commands::restart_computer,
            commands::cancel_computer_restart,
            commands::set_minimize_to_tray,
            commands::minimize_window_to_tray,
            commands::get_system_logs,
            commands::clear_system_logs,
            commands::get_diagnostic_report,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Simple Downloader");
}
