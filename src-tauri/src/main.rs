#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    let args: Vec<String> = std::env::args().collect();

    // If CLI arguments are provided (e.g. `internet-downloader.exe https://...`), run CLI mode!
    if args.len() > 1 {
        #[cfg(target_os = "windows")]
        unsafe {
            unsafe extern "system" {
                fn AttachConsole(dw_process_id: u32) -> i32;
            }
            AttachConsole(0xFFFFFFFF);
        }

        let rt = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("Failed to initialize async runtime");

        if let Err(e) = rt.block_on(internet_downloader_lib::cli::run_cli(args)) {
            eprintln!("\nError: {}", e);
            std::process::exit(1);
        }
        return;
    }

    // Default mode: Launch modern Tauri GUI
    internet_downloader_lib::run();
}
