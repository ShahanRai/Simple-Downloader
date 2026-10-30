use std::path::PathBuf;
use std::sync::Arc;
use tauri::State;
use tokio::sync::RwLock;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

use crate::engine::probe_url as engine_probe_url;
use crate::model::{DownloadStatus, DownloadTask, ProbeResult};
use crate::queue::QueueManager;

pub struct AppState {
    pub qm: Arc<RwLock<QueueManager>>,
    pub minimize_to_tray: Arc<std::sync::atomic::AtomicBool>,
}

#[tauri::command]
pub async fn set_minimize_to_tray(state: State<'_, AppState>, enabled: bool) -> Result<(), String> {
    state.minimize_to_tray.store(enabled, std::sync::atomic::Ordering::Relaxed);
    Ok(())
}

#[tauri::command]
pub async fn minimize_window_to_tray(window: tauri::Window) -> Result<(), String> {
    window.hide().map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_tasks(state: State<'_, AppState>) -> Result<Vec<DownloadTask>, String> {
    let qm = state.qm.read().await;
    Ok(qm.get_all_tasks())
}

#[tauri::command]
pub async fn probe_url(state: State<'_, AppState>, url: String) -> Result<ProbeResult, String> {
    if url.starts_with("magnet:") {
        return Ok(crate::torrent::probe_magnet(&url));
    }

    if crate::youtube::is_youtube_url(&url) {
        let u = url.clone();
        if let Ok(Ok(yt_res)) = tokio::task::spawn_blocking(move || crate::youtube::resolve_youtube(&u)).await {
            let first = yt_res.formats.first();
            let file_size = first.map(|f| f.size).unwrap_or(0);
            return Ok(ProbeResult {
                url: first.map(|f| f.url.clone()).unwrap_or(url),
                filename: format!("{}.mp4", crate::model::sanitize_filename(&yt_res.title)),
                file_size,
                accepts_ranges: true,
                etag: None,
                content_type: Some("video/mp4".to_string()),
            });
        }
    }

    let client = { state.qm.read().await.client.clone() };
    engine_probe_url(&client, &url)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn resolve_youtube(url: String) -> Result<crate::youtube::YouTubeResolveResult, String> {
    tokio::task::spawn_blocking(move || crate::youtube::resolve_youtube(&url))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn add_download(
    state: State<'_, AppState>,
    url: String,
    connections: Option<usize>,
    auto_start: Option<bool>,
    output_path: Option<String>,
) -> Result<DownloadTask, String> {
    QueueManager::add_task(
        state.qm.clone(),
        url,
        connections,
        auto_start.unwrap_or(true),
        output_path,
    )
    .await
    .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn pause_task(state: State<'_, AppState>, id: String) -> Result<bool, String> {
    let mut qm = state.qm.write().await;
    Ok(qm.pause_task(&id).await)
}

#[tauri::command]
pub async fn resume_task(state: State<'_, AppState>, id: String) -> Result<bool, String> {
    Ok(QueueManager::resume_task(state.qm.clone(), &id).await)
}

#[tauri::command]
pub async fn cancel_task(
    state: State<'_, AppState>,
    id: String,
    remove_files: Option<bool>,
) -> Result<bool, String> {
    let mut qm = state.qm.write().await;
    Ok(qm.cancel_task(&id, remove_files.unwrap_or(false)).await)
}

#[tauri::command]
pub async fn set_speed_limit(state: State<'_, AppState>, limit_bps: f64) -> Result<(), String> {
    let mut qm = state.qm.write().await;
    qm.set_speed_limit(limit_bps);
    Ok(())
}

#[tauri::command]
pub async fn get_speed_limit(state: State<'_, AppState>) -> Result<f64, String> {
    let qm = state.qm.read().await;
    Ok(qm.global_speed_limit_bps)
}

#[tauri::command]
pub async fn open_file(path: String) -> Result<(), String> {
    let p = PathBuf::from(&path);
    if p.exists() {
        open::that(&p).map_err(|e| e.to_string())
    } else {
        open_folder(path).await
    }
}

#[tauri::command]
pub async fn open_folder(path: String) -> Result<(), String> {
    let p = PathBuf::from(&path);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        if p.is_file() && p.exists() {
            let mut cmd = std::process::Command::new("explorer.exe");
            cmd.raw_arg(format!("/select,\"{}\"", p.to_string_lossy()));
            if cmd.spawn().is_ok() {
                return Ok(());
            }
        }

        let dir = if p.is_dir() && p.exists() {
            p
        } else if let Some(parent) = p.parent().filter(|par| par.exists()) {
            parent.to_path_buf()
        } else {
            let home = std::env::var("USERPROFILE").unwrap_or_else(|_| ".".to_string());
            PathBuf::from(home).join("Downloads")
        };

        let mut cmd = std::process::Command::new("explorer.exe");
        cmd.raw_arg(format!("\"{}\"", dir.to_string_lossy()));
        let _ = cmd.spawn();
        return Ok(());
    }
    #[cfg(not(target_os = "windows"))]
    {
        let dir = if p.is_dir() { p } else { p.parent().unwrap_or(Path::new(".")).to_path_buf() };
        open::that(dir).map_err(|e| e.to_string())
    }
}

#[tauri::command]
pub async fn open_extension_dir() -> Result<(), String> {
    let current_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let ext_dir = current_dir.join("browser_extension");
    if ext_dir.exists() {
        open::that(ext_dir).map_err(|e| e.to_string())
    } else {
        Err("Extension folder not found".to_string())
    }
}

#[tauri::command]
pub async fn get_default_download_dir(state: State<'_, AppState>) -> Result<String, String> {
    let qm = state.qm.read().await;
    Ok(qm.default_download_dir.to_string_lossy().to_string())
}

#[derive(serde::Serialize)]
pub struct DiskSpaceInfo {
    pub drive: String,
    pub free_bytes: u64,
    pub total_bytes: u64,
}

#[cfg(target_os = "windows")]
unsafe extern "system" {
    fn GetDiskFreeSpaceExW(
        lpDirectoryName: *const u16,
        lpFreeBytesAvailableToCaller: *mut u64,
        lpTotalNumberOfBytes: *mut u64,
        lpTotalNumberOfFreeBytes: *mut u64,
    ) -> i32;

    fn SetThreadExecutionState(esFlags: u32) -> u32;

    fn CoTaskMemFree(pv: *mut std::ffi::c_void);
    fn CoInitializeEx(pv_reserved: *mut std::ffi::c_void, dw_co_init: u32) -> i32;
    fn CoUninitialize();
}

#[tauri::command]
pub async fn get_disk_free_space(path: Option<String>) -> Result<DiskSpaceInfo, String> {
    #[cfg(target_os = "windows")]
    {
        let target_path = path.unwrap_or_else(|| "C:\\".to_string());
        let p = std::path::Path::new(&target_path);
        let drive_prefix = p
            .components()
            .next()
            .map(|c| c.as_os_str().to_string_lossy().to_string())
            .unwrap_or_else(|| "C:".to_string());

        let drive_root = if drive_prefix.ends_with('\\') || drive_prefix.ends_with('/') {
            drive_prefix.clone()
        } else {
            format!("{}\\", drive_prefix)
        };

        let wide: Vec<u16> = drive_root.encode_utf16().chain(std::iter::once(0)).collect();
        let mut free_avail: u64 = 0;
        let mut total: u64 = 0;
        let mut total_free: u64 = 0;

        let ret = unsafe {
            GetDiskFreeSpaceExW(
                wide.as_ptr(),
                &mut free_avail,
                &mut total,
                &mut total_free,
            )
        };

        if ret != 0 {
            Ok(DiskSpaceInfo {
                drive: drive_prefix.trim_end_matches('\\').trim_end_matches('/').to_string(),
                free_bytes: free_avail,
                total_bytes: total,
            })
        } else {
            let c_wide: Vec<u16> = "C:\\".encode_utf16().chain(std::iter::once(0)).collect();
            let ret2 = unsafe {
                GetDiskFreeSpaceExW(c_wide.as_ptr(), &mut free_avail, &mut total, &mut total_free)
            };
            if ret2 != 0 {
                Ok(DiskSpaceInfo {
                    drive: "C:".to_string(),
                    free_bytes: free_avail,
                    total_bytes: total,
                })
            } else {
                Err("Unable to query disk space".to_string())
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        Ok(DiskSpaceInfo {
            drive: "/".to_string(),
            free_bytes: 100_000_000_000,
            total_bytes: 500_000_000_000,
        })
    }
}

#[tauri::command]
pub fn set_run_on_startup(enable: bool) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        let current_exe = std::env::current_exe().map_err(|e| e.to_string())?;
        let exe_str = current_exe.to_string_lossy().to_string();
        if enable {
            let cmd = format!(
                r#"reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SimpleDownloader" /t REG_SZ /d "\"{}\"" /f"#,
                exe_str
            );
            let mut c = Command::new("cmd");
            c.arg("/C").arg(&cmd);
            c.creation_flags(0x08000000);
            let _ = c.output();
        } else {
            let mut c = Command::new("cmd");
            c.arg("/C").arg(r#"reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SimpleDownloader" /f"#);
            c.creation_flags(0x08000000);
            let _ = c.output();
        }
    }
    Ok(())
}

#[tauri::command]
pub fn get_run_on_startup() -> Result<bool, String> {
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        let mut c = Command::new("cmd");
        c.arg("/C").arg(r#"reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SimpleDownloader""#);
        c.creation_flags(0x08000000);
        if let Ok(out) = c.output() {
            return Ok(out.status.success());
        }
    }
    Ok(false)
}

#[tauri::command]
pub fn set_keep_pc_awake(active: bool) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    unsafe {
        if active {
            // ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            SetThreadExecutionState(0x80000000 | 0x00000001);
        } else {
            SetThreadExecutionState(0x80000000);
        }
    }
    Ok(())
}

#[tauri::command]
pub fn restart_computer() -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        let mut c = Command::new("shutdown");
        c.arg("/r").arg("/t").arg("60").arg("/c").arg("Simple Downloader: All downloads completed. Restarting in 60s.");
        c.creation_flags(0x08000000);
        let _ = c.output();
    }
    Ok(())
}

#[tauri::command]
pub fn cancel_computer_restart() -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        let mut c = Command::new("shutdown");
        c.arg("/a");
        c.creation_flags(0x08000000);
        let _ = c.output();
    }
    Ok(())
}

#[tauri::command]
pub async fn select_save_directory(_current_path: Option<String>) -> Result<Option<String>, String> {
    #[cfg(target_os = "windows")]
    {
        let (tx, rx) = tokio::sync::oneshot::channel();
        std::thread::spawn(move || {
            let res = pick_folder_win32();
            let _ = tx.send(res);
        });
        rx.await.map_err(|e| e.to_string())
    }
    #[cfg(not(target_os = "windows"))]
    {
        Ok(None)
    }
}

#[cfg(target_os = "windows")]
fn pick_folder_win32() -> Option<String> {
    use std::ptr;
    unsafe {
        CoInitializeEx(ptr::null_mut(), 0x2);

        #[repr(C)]
        #[derive(Clone, Copy)]
        struct GUID {
            data1: u32,
            data2: u16,
            data3: u16,
            data4: [u8; 8],
        }

        const CLSID_FILE_OPEN_DIALOG: GUID = GUID {
            data1: 0xDC1C5A9C,
            data2: 0xE88A,
            data3: 0x4DDE,
            data4: [0xA5, 0xA1, 0x60, 0xF8, 0x2A, 0x20, 0xAE, 0xF7],
        };

        const IID_IFILE_DIALOG: GUID = GUID {
            data1: 0x42f85136,
            data2: 0xdb7e,
            data3: 0x439c,
            data4: [0x85, 0xf1, 0xe4, 0x07, 0x5d, 0x13, 0x5f, 0xc8],
        };

        const FOS_PICKFOLDERS: u32 = 0x20;
        const FOS_FORCEFILESYSTEM: u32 = 0x40;
        const FOS_PATHMUSTEXIST: u32 = 0x800;
        const SIGDN_FILESYSPATH: u32 = 0x80058000;

        unsafe extern "system" {
            fn CoCreateInstance(
                rclsid: *const GUID,
                p_unk_outer: *mut std::ffi::c_void,
                dw_cls_context: u32,
                riid: *const GUID,
                ppv: *mut *mut std::ffi::c_void,
            ) -> i32;
        }

        let mut dialog: *mut std::ffi::c_void = ptr::null_mut();
        let hr = CoCreateInstance(
            &CLSID_FILE_OPEN_DIALOG,
            ptr::null_mut(),
            1, // CLSCTX_INPROC_SERVER
            &IID_IFILE_DIALOG,
            &mut dialog,
        );

        if hr != 0 || dialog.is_null() {
            CoUninitialize();
            return None;
        }

        let vtable = *(dialog as *const *const usize);

        type SetOptionsFn = unsafe extern "system" fn(*mut std::ffi::c_void, u32) -> i32;
        type SetTitleFn = unsafe extern "system" fn(*mut std::ffi::c_void, *const u16) -> i32;
        type ShowFn = unsafe extern "system" fn(*mut std::ffi::c_void, *mut std::ffi::c_void) -> i32;
        type GetResultFn = unsafe extern "system" fn(*mut std::ffi::c_void, *mut *mut std::ffi::c_void) -> i32;
        type ReleaseFn = unsafe extern "system" fn(*mut std::ffi::c_void) -> u32;

        let set_options: SetOptionsFn = std::mem::transmute(*vtable.add(9));
        let set_title: SetTitleFn = std::mem::transmute(*vtable.add(17));
        let show: ShowFn = std::mem::transmute(*vtable.add(3));
        let get_result: GetResultFn = std::mem::transmute(*vtable.add(20));
        let release: ReleaseFn = std::mem::transmute(*vtable.add(2));

        let options = FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST;
        let _ = set_options(dialog, options);

        let title: Vec<u16> = "Select Download Directory\0".encode_utf16().collect();
        let _ = set_title(dialog, title.as_ptr());

        let show_res = show(dialog, ptr::null_mut());

        let mut selected_path: Option<String> = None;
        if show_res == 0 {
            let mut shell_item: *mut std::ffi::c_void = ptr::null_mut();
            if get_result(dialog, &mut shell_item) == 0 && !shell_item.is_null() {
                let item_vtable = *(shell_item as *const *const usize);
                type GetDisplayNameFn = unsafe extern "system" fn(*mut std::ffi::c_void, u32, *mut *mut u16) -> i32;
                type ItemReleaseFn = unsafe extern "system" fn(*mut std::ffi::c_void) -> u32;

                let get_display_name: GetDisplayNameFn = std::mem::transmute(*item_vtable.add(5));
                let item_release: ItemReleaseFn = std::mem::transmute(*item_vtable.add(2));

                let mut path_ptr: *mut u16 = ptr::null_mut();
                if get_display_name(shell_item, SIGDN_FILESYSPATH, &mut path_ptr) == 0 && !path_ptr.is_null() {
                    let mut len = 0;
                    while *path_ptr.add(len) != 0 {
                        len += 1;
                    }
                    let slice = std::slice::from_raw_parts(path_ptr, len);
                    selected_path = Some(String::from_utf16_lossy(slice));
                    CoTaskMemFree(path_ptr as *mut std::ffi::c_void);
                }
                item_release(shell_item);
            }
        }

        release(dialog);
        CoUninitialize();
        selected_path
    }
}

#[tauri::command]
pub async fn minimize_window(window: tauri::Window) -> Result<(), String> {
    window.minimize().map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn toggle_maximize_window(window: tauri::Window) -> Result<(), String> {
    if window.is_maximized().unwrap_or(false) {
        window.unmaximize().map_err(|e| e.to_string())
    } else {
        window.maximize().map_err(|e| e.to_string())
    }
}

#[tauri::command]
pub async fn close_window(window: tauri::Window) -> Result<(), String> {
    window.close().map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn delete_tasks(
    state: State<'_, AppState>,
    ids: Vec<String>,
    remove_files: Option<bool>,
) -> Result<u32, String> {
    let mut qm = state.qm.write().await;
    let rf = remove_files.unwrap_or(false);
    let mut count = 0u32;
    for id in &ids {
        if qm.cancel_task(id, rf).await {
            count += 1;
        }
    }
    Ok(count)
}

#[tauri::command]
pub async fn start_dragging(window: tauri::Window) -> Result<(), String> {
    window.start_dragging().map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_system_logs() -> Result<Vec<crate::logger::LogEntry>, String> {
    Ok(crate::logger::get_all_logs())
}

#[tauri::command]
pub async fn clear_system_logs() -> Result<(), String> {
    crate::logger::clear_all_logs();
    Ok(())
}

#[tauri::command]
pub async fn get_diagnostic_report(state: State<'_, AppState>) -> Result<String, String> {
    let qm = state.qm.read().await;
    let total = qm.tasks.len();
    let downloading = qm.tasks.values().filter(|t| t.status == DownloadStatus::DOWNLOADING).count();
    let paused = qm.tasks.values().filter(|t| t.status == DownloadStatus::PAUSED).count();
    let completed = qm.tasks.values().filter(|t| t.status == DownloadStatus::COMPLETED).count();
    let failed = qm.tasks.values().filter(|t| t.status == DownloadStatus::FAILED).count();
    let summary = format!("Total: {}, Downloading: {}, Paused: {}, Completed: {}, Failed: {}", total, downloading, paused, completed, failed);
    let os_info = "Windows x64 - Simple Downloader v1.0.0".to_string();
    Ok(crate::logger::get_diagnostic_report(&os_info, &summary))
}
