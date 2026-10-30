/**
 * Simple Downloader - High-Speed Multi-Stream Acceleration Engine
 * Executive-Grade Frontend Controller (Zero-Flicker, Real Disk Space, Preferences & Magnet Support)
 */

// Visualizer Spectrum for 1..32 Parallel Streams
const STREAM_COLORS = [
  "#2563eb", "#7c3aed", "#10b981", "#f59e0b",
  "#ec4899", "#3b82f6", "#8b5cf6", "#14b8a6",
  "#f97316", "#06b6d4", "#6366f1", "#84cc16"
];

// Reactive Application State
const state = {
  tasks: [],
  selectedTaskId: null,
  checkedTaskIds: new Set(),
  activeCategory: "all",
  searchQuery: "",
  theme: localStorage.getItem("theme") || "dark",
  defaultDownloadDir: "",
  isTauri: false,
  lastRenderedKey: "",
  // Advanced preferences
  runOnStartup: false,
  minimizeToTray: localStorage.getItem("pref_minimize_tray") === "true",
  keepPcAwake: localStorage.getItem("pref_keep_awake") === "true",
  restartOnComplete: localStorage.getItem("pref_restart_complete") === "true",
  defaultConnections: parseInt(localStorage.getItem("pref_default_connections") || "16", 10),
  hasRestarted: false,
  pendingDeleteIds: new Set(),
  globalSpeedLimitBps: parseFloat(localStorage.getItem("pref_speed_limit_bps") || "0")
};

if (window.__TAURI__ || window.__TAURI_INTERNALS__) {
  state.isTauri = true;
}

// IPC Wrapper with Tauri Core & HTTP Fallbacks
async function invokeTauri(cmd, args = {}) {
  try {
    if (window.__TAURI__ && window.__TAURI__.core && window.__TAURI__.core.invoke) {
      return await window.__TAURI__.core.invoke(cmd, args);
    } else if (window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke) {
      return await window.__TAURI_INTERNALS__.invoke(cmd, args);
    }
  } catch (err) {
    console.warn(`IPC '${cmd}' warning:`, err);
    throw err;
  }

  // Local HTTP API Fallback
  try {
    if (cmd === "get_tasks") {
      const res = await fetch("http://127.0.0.1:9653/tasks");
      const data = await res.json();
      return data.tasks || [];
    } else if (cmd === "add_download") {
      const res = await fetch("http://127.0.0.1:9653/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args)
      });
      return await res.json();
    } else if (cmd === "pause_task") {
      await fetch(`http://127.0.0.1:9653/task/${args.id}/pause`, { method: "POST" });
      return true;
    } else if (cmd === "resume_task") {
      await fetch(`http://127.0.0.1:9653/task/${args.id}/resume`, { method: "POST" });
      return true;
    } else if (cmd === "cancel_task") {
      await fetch(`http://127.0.0.1:9653/task/${args.id}/cancel`, { method: "POST" });
      return true;
    } else if (cmd === "set_speed_limit") {
      await fetch("http://127.0.0.1:9653/speed_limit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args)
      });
      return true;
    } else if (cmd === "get_speed_limit") {
      const res = await fetch("http://127.0.0.1:9653/speed_limit");
      const data = await res.json();
      return data.limit_bps || 0;
    }
  } catch (_) {}
  return null;
}

// Formatters
function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let b = bytes;
  while (b >= 1024 && i < units.length - 1) {
    b /= 1024;
    i++;
  }
  return `${b.toFixed(i === 0 ? 0 : (b < 10 ? 2 : 1))} ${units[i]}`;
}

function formatSpeed(bps) {
  if (!bps || bps <= 0) return "0.0 KB/s";
  return `${formatBytes(bps)}/s`;
}

function formatTime(seconds) {
  if (!seconds || seconds <= 0 || !isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs.toString().padStart(2, "0")}s`;
  }
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hrs}h ${mins}m`;
}

// Real Disk Space Updater
async function updateDiskSpace(path) {
  const label = document.getElementById("quick-disk-space");
  if (!label) return;

  try {
    const res = await invokeTauri("get_disk_free_space", { path: path || state.defaultDownloadDir || undefined });
    if (res && res.free_bytes) {
      label.textContent = `Free space (${res.drive || 'C:'}): ${formatBytes(res.free_bytes)}`;
      return;
    }
  } catch (err) {
    console.warn("get_disk_free_space error:", err);
  }
  label.textContent = "Free space (C:): Available";
}

// Confirmation Dialog Modal
function showConfirmDialog({ title, message, confirmText = "Confirm", isDanger = true, showFileOption = false }) {
  return new Promise((resolve) => {
    const modal = document.getElementById("modal-confirm-dialog");
    const titleEl = document.getElementById("confirm-dialog-title");
    const msgEl = document.getElementById("confirm-dialog-message");
    const okBtn = document.getElementById("confirm-btn-ok");
    const cancelBtn = document.getElementById("confirm-btn-cancel");
    const iconDanger = document.getElementById("confirm-icon-danger");
    const iconInfo = document.getElementById("confirm-icon-info");
    const iconWrap = document.getElementById("confirm-dialog-icon-wrap");
    const fileOptLabel = document.getElementById("confirm-dialog-file-option");
    const deleteDiskCheck = document.getElementById("confirm-delete-disk-file");

    if (titleEl) titleEl.textContent = title || "Confirmation";
    if (msgEl) msgEl.textContent = message || "Are you sure you want to proceed?";
    if (okBtn) okBtn.textContent = confirmText;

    if (fileOptLabel) {
      fileOptLabel.style.display = showFileOption ? "flex" : "none";
    }
    if (deleteDiskCheck) {
      deleteDiskCheck.checked = false;
    }

    if (isDanger) {
      if (okBtn) okBtn.className = "btn-primary btn-danger";
      if (iconWrap) iconWrap.className = "modal-icon-badge modal-icon-danger";
      if (iconDanger) iconDanger.style.display = "block";
      if (iconInfo) iconInfo.style.display = "none";
    } else {
      if (okBtn) okBtn.className = "btn-primary";
      if (iconWrap) iconWrap.className = "modal-icon-badge";
      if (iconDanger) iconDanger.style.display = "none";
      if (iconInfo) iconInfo.style.display = "block";
    }

    if (modal) modal.classList.add("open");

    const cleanup = () => {
      if (modal) modal.classList.remove("open");
      okBtn?.removeEventListener("click", onOk);
      cancelBtn?.removeEventListener("click", onCancel);
    };

    const onOk = () => {
      const deleteFile = deleteDiskCheck ? deleteDiskCheck.checked : false;
      cleanup();
      resolve({ confirmed: true, deleteFile });
    };

    const onCancel = () => {
      cleanup();
      resolve({ confirmed: false, deleteFile: false });
    };

    okBtn?.addEventListener("click", onOk);
    cancelBtn?.addEventListener("click", onCancel);
  });
}

// Seamless Theme Switching
function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.setAttribute("data-theme", theme);

  if (theme === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
  localStorage.setItem("theme", theme);

  const moonIcon = document.getElementById("theme-icon-moon");
  const sunIcon = document.getElementById("theme-icon-sun");
  if (moonIcon && sunIcon) {
    if (theme === "dark") {
      moonIcon.style.display = "none";
      sunIcon.style.display = "block";
    } else {
      moonIcon.style.display = "block";
      sunIcon.style.display = "none";
    }
  }

  updateNavActiveClasses();
  state.lastRenderedKey = "";
  renderTasksTable();
}

function updateNavActiveClasses() {
  const isDark = state.theme === "dark";

  // Filter Bar Tabs
  document.querySelectorAll(".filter-tab-btn").forEach(btn => {
    const cat = btn.getAttribute("data-category") || "all";
    const isActive = cat === state.activeCategory;

    if (isActive) {
      btn.className = isDark
        ? "nav-item filter-tab-btn active px-2.5 h-6 rounded-md bg-[#1f232c] text-[#f3f4f6] text-xs font-medium transition-colors border border-[#282d38] shadow-xs"
        : "nav-item filter-tab-btn active px-2.5 h-6 rounded-md bg-[#6366f1] text-white text-xs font-medium transition-colors border border-transparent shadow-xs";
    } else {
      btn.className = isDark
        ? "nav-item filter-tab-btn px-2.5 h-6 rounded-md hover:bg-[#1f232c] text-[#9ca3af] hover:text-[#f3f4f6] text-xs transition-colors border border-transparent"
        : "nav-item filter-tab-btn px-2.5 h-6 rounded-md hover:bg-[#f1f5f9] text-[#64748b] hover:text-[#0f172a] text-xs transition-colors border border-transparent";
    }
  });

  // Sidebar Links
  document.querySelectorAll("#sidebar-nav .nav-item").forEach(link => {
    const cat = link.getAttribute("data-category") || "all";
    const isActive = (cat === state.activeCategory) || (state.activeCategory !== "completed" && cat === "all");

    if (isActive) {
      link.classList.add("active");
      if (isDark) {
        link.className = "nav-item active flex items-center gap-2 px-2.5 py-1.5 rounded-md transition-all duration-150 bg-[#1f232c] text-[#f3f4f6] text-xs font-semibold shadow-xs border border-[#282d38] w-full text-left cursor-pointer";
      } else {
        link.className = "nav-item active flex items-center gap-2 px-2.5 py-1.5 rounded-md transition-all duration-150 bg-[#e0e7ff]/70 text-[#4f46e5] text-xs font-semibold shadow-xs border border-[#c7d2fe]/50 w-full text-left cursor-pointer";
      }
    } else {
      link.classList.remove("active");
      link.className = isDark
        ? "nav-item flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[#9ca3af] hover:bg-[#161920] hover:text-[#f3f4f6] text-xs transition-colors w-full text-left border border-transparent cursor-pointer"
        : "nav-item flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[#64748b] hover:bg-[#f1f5f9] hover:text-[#0f172a] text-xs transition-colors w-full text-left border border-transparent cursor-pointer";
    }
  });
}

// App Initialization
document.addEventListener("DOMContentLoaded", async () => {
  applyTheme(state.theme);
  setupWindowDragAndControls();
  setupEventListeners();
  initSpeedLimiter();

  // Load default download directory
  try {
    const dir = await invokeTauri("get_default_download_dir");
    if (dir) {
      state.defaultDownloadDir = dir;
      updateDestinationLabels(dir);
      updateDiskSpace(dir);
    }
  } catch (err) {
    console.warn("Default dir error:", err);
  }

  // Load Run on Startup status
  try {
    const autostart = await invokeTauri("get_run_on_startup");
    state.runOnStartup = !!autostart;
    const cb = document.getElementById("settings-launch-startup");
    if (cb) cb.checked = state.runOnStartup;
  } catch (_) {}

  // Load other preferences
  const trayCb = document.getElementById("settings-minimize-tray");
  if (trayCb) trayCb.checked = state.minimizeToTray;
  invokeTauri("set_minimize_to_tray", { enabled: state.minimizeToTray }).catch(() => {});

  const awakeCb = document.getElementById("settings-keep-awake");
  if (awakeCb) awakeCb.checked = state.keepPcAwake;

  const restartCb = document.getElementById("settings-restart-complete");
  if (restartCb) restartCb.checked = state.restartOnComplete;

  // Real-time Event Listener from Tauri Core
  if (window.__TAURI__ && window.__TAURI__.event && window.__TAURI__.event.listen) {
    try {
      window.__TAURI__.event.listen("download-progress", (event) => {
        handleProgressEvent(event.payload);
      });

      // Windows Clipboard URL Detection Listener
      window.__TAURI__.event.listen("clipboard-download-detected", (event) => {
        const data = event.payload;
        if (!data || !data.url) return;
        const sniffEnabled = document.getElementById("settings-clipboard-sniff")?.checked ?? true;
        if (!sniffEnabled) return;

        // Populate capture fields so user can review and explicitly start
        const input = document.getElementById("quick-url-input");
        if (input && !input.value) {
          input.value = data.url;
        }

        const modalInput = document.getElementById("input-download-url");
        if (modalInput && !modalInput.value) {
          modalInput.value = data.url;
          probeUrl(data.url);
        }

        const modalAdd = document.getElementById("modal-add-download");
        const modalSettings = document.getElementById("modal-settings");
        if (modalAdd && !modalAdd.classList.contains("active") && modalSettings && !modalSettings.classList.contains("active")) {
          openAddModal();
        }
      });
    } catch (_) {}
  }

  // Initial refresh
  await refreshTasks();

  // Non-destructive polling loop (1000ms)
  setInterval(refreshTasks, 1000);

  // Auto-inspect clipboard preview button
  checkClipboardPreview();
});

// Destination Labels
function updateDestinationLabels(path) {
  if (!path) return;
  const quickLabel = document.getElementById("quick-destination-label");
  if (quickLabel) {
    const clean = path.replace(/\\/g, '/');
    const parts = clean.split('/').filter(Boolean);
    quickLabel.textContent = parts.length > 0 ? `~/${parts[parts.length - 1]}` : "~/Downloads";
    quickLabel.title = path;
  }
  const saveInput = document.getElementById("input-save-path");
  if (saveInput && !saveInput.value) saveInput.value = path;
  const settingsDir = document.getElementById("settings-default-dir");
  if (settingsDir) settingsDir.value = path;
}

// Themed Custom Dropdown Initializer
function setupCustomSelect(wrapperId, triggerBtnId, menuId, labelId, hiddenInputId) {
  const btn = document.getElementById(triggerBtnId);
  const menu = document.getElementById(menuId);
  const label = document.getElementById(labelId);
  const hiddenInput = document.getElementById(hiddenInputId);

  if (!btn || !menu || !label || !hiddenInput) return;

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = menu.style.display !== "none";
    // Close other dropdowns
    document.querySelectorAll(".custom-select-menu").forEach(m => m.style.display = "none");
    document.querySelectorAll(".custom-select-btn").forEach(b => b.classList.remove("open"));
    const dm = document.getElementById("quick-destination-menu");
    if (dm) {
      dm.classList.add("hidden");
      dm.classList.remove("flex");
    }
    const arr = document.getElementById("quick-destination-arrow");
    if (arr) arr.style.transform = "";

    if (!isOpen) {
      menu.style.display = "flex";
      btn.classList.add("open");
    } else {
      menu.style.display = "none";
      btn.classList.remove("open");
    }
  });

  menu.querySelectorAll(".custom-select-item").forEach(item => {
    item.addEventListener("click", (e) => {
      e.stopPropagation();
      const val = item.dataset.value;
      const text = item.textContent.replace("✔", "").trim();
      hiddenInput.value = val;
      label.textContent = text;

      menu.querySelectorAll(".custom-select-item").forEach(i => i.classList.remove("active"));
      item.classList.add("active");

      menu.style.display = "none";
      btn.classList.remove("open");
    });
  });
}

// Window Titlebar Dragging & Controls
function setupWindowDragAndControls() {
  const titlebar = document.getElementById("app-titlebar");

  titlebar?.addEventListener("mousedown", (e) => {
    if (e.button === 0 && !e.target.closest("button, input, select, a, label, [onclick]")) {
      invokeTauri("start_dragging").catch(() => {});
    }
  });

  document.getElementById("win-minimize")?.addEventListener("click", () => {
    invokeTauri("minimize_window").catch(() => {});
  });

  document.getElementById("win-maximize")?.addEventListener("click", () => {
    invokeTauri("toggle_maximize_window").catch(() => {});
  });

  document.getElementById("win-close")?.addEventListener("click", () => {
    if (state.minimizeToTray) {
      invokeTauri("minimize_window_to_tray").catch(() => {});
    } else {
      invokeTauri("close_window").catch(() => {});
    }
  });

  document.getElementById("btn-theme-toggle")?.addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  });
}

// Check Clipboard Preview
async function checkClipboardPreview() {
  try {
    const text = await navigator.clipboard.readText();
    if (text && (text.startsWith("http://") || text.startsWith("https://") || text.startsWith("magnet:"))) {
      const quickBtn = document.getElementById("quick-btn-clipboard");
      if (quickBtn) {
        quickBtn.classList.add("ring-1", "ring-[#6366f1]/50");
      }
    }
  } catch (_) {}
}

// Event Listeners Setup
function setupEventListeners() {
  // Modal Openers
  document.getElementById("btn-add-download")?.addEventListener("click", () => openAddModal());
  document.getElementById("btn-empty-add")?.addEventListener("click", () => openAddModal());
  document.getElementById("btn-open-settings")?.addEventListener("click", () => {
    // Sync current values to settings modal inputs
    const dirInput = document.getElementById("settings-default-dir");
    if (dirInput && state.defaultDownloadDir) dirInput.value = state.defaultDownloadDir;

    const startupCb = document.getElementById("settings-launch-startup");
    if (startupCb) startupCb.checked = !!state.runOnStartup;

    const trayCb = document.getElementById("settings-minimize-tray");
    if (trayCb) trayCb.checked = !!state.minimizeToTray;

    const awakeCb = document.getElementById("settings-keep-awake");
    if (awakeCb) awakeCb.checked = !!state.keepPcAwake;

    const restartCb = document.getElementById("settings-restart-complete");
    if (restartCb) restartCb.checked = !!state.restartOnComplete;

    const connections = state.defaultConnections || 16;
    const hiddenConn = document.getElementById("settings-default-connections");
    if (hiddenConn) hiddenConn.value = String(connections);
    const labelConn = document.getElementById("label-settings-streams");
    if (labelConn) labelConn.textContent = `${connections} Streams${connections === 16 ? " (Recommended)" : ""}`;

    const menu = document.getElementById("menu-settings-streams");
    if (menu) {
      menu.querySelectorAll(".custom-select-item").forEach(item => {
        if (item.dataset.value === String(connections)) item.classList.add("active");
        else item.classList.remove("active");
      });
    }

    const bps = state.globalSpeedLimitBps || 0;
    const settingsVal = document.getElementById("settings-speed-limit-val");
    const settingsUnit = document.getElementById("settings-speed-limit-unit");
    if (settingsVal && settingsUnit) {
      if (bps === 0) {
        settingsVal.value = "";
      } else if (bps >= 1048576) {
        settingsVal.value = (bps / (1024 * 1024)).toFixed(1).replace(/\.0$/, "");
        settingsUnit.value = "MB";
      } else {
        settingsVal.value = Math.round(bps / 1024);
        settingsUnit.value = "KB";
      }
    }

    openModal("modal-settings");
  });
  document.getElementById("btn-open-extension-folder")?.addEventListener("click", () => invokeTauri("open_extension_dir"));
  document.getElementById("btn-open-logs")?.addEventListener("click", openLogsModal);
  document.getElementById("btn-copy-logs")?.addEventListener("click", copyDetailedLogs);
  document.getElementById("btn-clear-logs")?.addEventListener("click", clearLogs);
  document.getElementById("log-search-filter")?.addEventListener("input", renderFilteredLogs);
  document.getElementById("log-level-filter")?.addEventListener("change", renderFilteredLogs);

  // Modal Closers
  document.querySelectorAll("[data-close-modal]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-close-modal");
      if (id === "modal-logs-dialog") {
        closeLogsModal();
      } else {
        closeModal(id);
      }
    });
  });

  // Filter Tabs & Sidebar Navigation
  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", (e) => {
      e.preventDefault();
      const cat = item.getAttribute("data-category") || "all";
      state.activeCategory = cat;
      updateNavActiveClasses();
      state.lastRenderedKey = "";
      renderTasksTable();
    });
  });

  // Search Filter
  document.getElementById("input-search")?.addEventListener("input", (e) => {
    state.searchQuery = e.target.value.toLowerCase().trim();
    state.lastRenderedKey = "";
    renderTasksTable();
  });

  // Keyboard Shortcut: Ctrl+K / Cmd+K
  window.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      const s = document.getElementById("input-search");
      if (s) {
        s.focus();
        s.select();
      }
    }
  });

  // Toolbar Actions: Resume All / Pause All / Clear All
  document.getElementById("btn-resume-selected")?.addEventListener("click", async () => {
    const targetIds = state.checkedTaskIds.size > 0
      ? Array.from(state.checkedTaskIds)
      : state.tasks.filter(t => t.status === "PAUSED" || t.status === "FAILED").map(t => t.id);

    for (const id of targetIds) {
      const t = state.tasks.find(x => x.id === id);
      if (t) {
        t.status = "DOWNLOADING";
        updateTableRow(t);
      }
      invokeTauri("resume_task", { id }).catch(() => {});
    }
    updateGlobalMetrics();
    updateSidebarBadges();
  });

  document.getElementById("btn-pause-selected")?.addEventListener("click", async () => {
    const targetIds = state.checkedTaskIds.size > 0
      ? Array.from(state.checkedTaskIds)
      : state.tasks.filter(t => t.status === "DOWNLOADING").map(t => t.id);

    for (const id of targetIds) {
      const t = state.tasks.find(x => x.id === id);
      if (t) {
        t.status = "PAUSED";
        t.speed_bps = 0.0;
        updateTableRow(t);
      }
      invokeTauri("pause_task", { id }).catch(() => {});
    }
    updateGlobalMetrics();
    updateSidebarBadges();
  });

  document.getElementById("btn-delete-selected")?.addEventListener("click", async () => {
    const isClearingAll = state.checkedTaskIds.size === 0;
    const count = isClearingAll ? state.tasks.length : state.checkedTaskIds.size;
    if (count === 0) return;

    const res = await showConfirmDialog({
      title: isClearingAll ? "Clear Download Queue" : "Delete Selected Downloads",
      message: isClearingAll
        ? "Remove all downloads from the queue?"
        : `Remove ${count} selected download${count > 1 ? 's' : ''} from the queue?`,
      confirmText: "Delete",
      isDanger: true,
      showFileOption: true
    });

    if (res && res.confirmed) {
      const ids = isClearingAll ? state.tasks.map(t => t.id) : Array.from(state.checkedTaskIds);
      ids.forEach(id => state.pendingDeleteIds.add(id));
      setTimeout(() => ids.forEach(id => state.pendingDeleteIds.delete(id)), 6000);
      // Immediately remove from UI for instant response
      const idSet = new Set(ids);
      state.tasks = state.tasks.filter(t => !idSet.has(t.id));
      state.checkedTaskIds.clear();
      state.selectedTaskId = null;
      state.lastRenderedKey = "";
      renderTasksTable();
      updateSidebarBadges();
      updateGlobalMetrics();

      try {
        await invokeTauri("delete_tasks", { ids, removeFiles: res.deleteFile });
      } catch (err) {
        console.error("delete_tasks error:", err);
      }
      refreshTasks();
    }
  });

  // Top URL Quick Capture Actions
  const handleQuickDownload = async () => {
    const input = document.getElementById("quick-url-input");
    const url = input?.value.trim();
    if (!url) {
      openAddModal();
      return;
    }

    const autoStart = document.getElementById("quick-auto-start")?.checked ?? true;
    const savePath = state.defaultDownloadDir || undefined;

    try {
      const task = await invokeTauri("add_download", {
        url,
        connections: 16,
        autoStart,
        outputPath: savePath
      });

      if (task && task.id) {
        state.selectedTaskId = task.id;
      }
      if (input) input.value = "";
      state.lastRenderedKey = "";
      refreshTasks();
    } catch (err) {
      openAddModal();
      const modalUrl = document.getElementById("input-download-url");
      if (modalUrl) {
        modalUrl.value = url;
        probeUrl(url);
      }
      const errorMsg = document.getElementById("modal-error-message");
      const errorBanner = document.getElementById("modal-error-banner");
      if (errorMsg && errorBanner) {
        errorMsg.textContent = typeof err === "string" ? err : (err.message || "Failed to start download");
        errorBanner.style.display = "flex";
      }
    }
  };

  document.getElementById("quick-btn-download")?.addEventListener("click", handleQuickDownload);
  document.getElementById("quick-url-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleQuickDownload();
  });

  document.getElementById("quick-btn-clipboard")?.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        const input = document.getElementById("quick-url-input");
        if (input) {
          input.value = text.trim();
          input.focus();
        }
      }
    } catch (e) {
      console.warn("Clipboard access:", e);
    }
  });

  // Fast & Instant Folder Browse & Quick Destination Menu
  const destBtn = document.getElementById("quick-destination-btn");
  const destMenu = document.getElementById("quick-destination-menu");
  const destArrow = document.getElementById("quick-destination-arrow");

  destBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!destMenu) return;
    const isHidden = destMenu.classList.contains("hidden");
    // Close other open menus
    document.querySelectorAll(".custom-select-menu").forEach(m => m.style.display = "none");
    document.querySelectorAll(".custom-select-btn").forEach(b => b.classList.remove("open"));

    if (isHidden) {
      destMenu.classList.remove("hidden");
      destMenu.classList.add("flex");
      if (destArrow) destArrow.style.transform = "rotate(180deg)";
    } else {
      destMenu.classList.add("hidden");
      destMenu.classList.remove("flex");
      if (destArrow) destArrow.style.transform = "";
    }
  });

  // Handle Quick Locations inside dropdown
  document.querySelectorAll(".dest-menu-item").forEach(item => {
    item.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (destMenu) {
        destMenu.classList.add("hidden");
        destMenu.classList.remove("flex");
      }
      if (destArrow) destArrow.style.transform = "";

      const target = item.dataset.target;
      const baseDir = state.defaultDownloadDir || "C:\\Users\\Default\\Downloads";
      const userDir = baseDir.replace(/\\Downloads$/i, "").replace(/\/Downloads$/i, "");
      let path = "";

      if (target === "downloads") {
        path = /Downloads/i.test(baseDir) ? baseDir : `${userDir}\\Downloads`;
      } else if (target === "desktop") {
        path = `${userDir}\\Desktop`;
      } else if (target === "videos") {
        path = `${userDir}\\Videos`;
      } else if (target === "documents") {
        path = `${userDir}\\Documents`;
      }

      if (path) {
        state.defaultDownloadDir = path;
        updateDestinationLabels(path);
        updateDiskSpace(path);
      }
    });
  });

  // Handle Browse Custom Folder inside destination dropdown
  document.getElementById("dest-menu-browse-btn")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (destMenu) {
      destMenu.classList.add("hidden");
      destMenu.classList.remove("flex");
    }
    if (destArrow) destArrow.style.transform = "";

    try {
      const selected = await invokeTauri("select_save_directory", { currentPath: state.defaultDownloadDir || undefined });
      if (selected) {
        state.defaultDownloadDir = selected;
        updateDestinationLabels(selected);
        updateDiskSpace(selected);
      }
    } catch (err) {
      console.error("Browse directory error:", err);
    }
  });

  // Setup Custom Selects for Streams
  setupCustomSelect("custom-select-settings-streams", "btn-trigger-settings-streams", "menu-settings-streams", "label-settings-streams", "settings-default-connections");
  setupCustomSelect("custom-select-add-streams", "btn-trigger-add-streams", "menu-add-streams", "label-add-streams", "select-connections");

  // Global Click Dismiss for Dropdowns
  document.addEventListener("click", () => {
    document.querySelectorAll(".custom-select-menu").forEach(m => m.style.display = "none");
    document.querySelectorAll(".custom-select-btn").forEach(b => b.classList.remove("open"));
    if (destMenu) {
      destMenu.classList.add("hidden");
      destMenu.classList.remove("flex");
      if (destArrow) destArrow.style.transform = "";
    }
    const speedMenu = document.getElementById("speed-limiter-menu");
    if (speedMenu && !speedMenu.classList.contains("hidden")) {
      speedMenu.classList.add("hidden");
      speedMenu.classList.remove("flex");
      const speedArrow = document.getElementById("speed-limiter-arrow");
      if (speedArrow) speedArrow.style.transform = "";
    }
  });

  // Modal Add Actions
  document.getElementById("btn-paste-url")?.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        document.getElementById("input-download-url").value = text.trim();
        probeUrl(text.trim());
      }
    } catch (e) {
      console.warn("Clipboard access:", e);
    }
  });

  document.getElementById("btn-probe-url")?.addEventListener("click", () => {
    const url = document.getElementById("input-download-url").value.trim();
    if (url) probeUrl(url);
  });

  document.getElementById("input-download-url")?.addEventListener("change", (e) => {
    const url = e.target.value.trim();
    if (url) probeUrl(url);
  });

  document.getElementById("btn-browse-folder")?.addEventListener("click", async () => {
    const current = document.getElementById("input-save-path").value.trim();
    try {
      const selected = await invokeTauri("select_save_directory", { currentPath: current || state.defaultDownloadDir || undefined });
      if (selected) {
        document.getElementById("input-save-path").value = selected;
        state.defaultDownloadDir = selected;
        updateDestinationLabels(selected);
        updateDiskSpace(selected);
      }
    } catch (err) {
      console.error("Browse directory error:", err);
    }
  });

  document.getElementById("btn-settings-browse")?.addEventListener("click", async () => {
    const current = document.getElementById("settings-default-dir").value.trim();
    try {
      const selected = await invokeTauri("select_save_directory", { currentPath: current || state.defaultDownloadDir || undefined });
      if (selected) {
        document.getElementById("settings-default-dir").value = selected;
        state.defaultDownloadDir = selected;
        updateDestinationLabels(selected);
        updateDiskSpace(selected);
      }
    } catch (err) {
      console.error("Browse settings directory error:", err);
    }
  });

  // Save Preferences
  document.getElementById("btn-save-settings")?.addEventListener("click", async () => {
    const dir = document.getElementById("settings-default-dir")?.value.trim();
    if (dir) {
      state.defaultDownloadDir = dir;
      updateDestinationLabels(dir);
      updateDiskSpace(dir);
    }

    // Save Run on Startup
    const startupCb = document.getElementById("settings-launch-startup");
    if (startupCb) {
      const enable = startupCb.checked;
      state.runOnStartup = enable;
      invokeTauri("set_run_on_startup", { enable }).catch(() => {});
    }

    // Save Minimize to Tray
    const trayCb = document.getElementById("settings-minimize-tray");
    if (trayCb) {
      state.minimizeToTray = trayCb.checked;
      localStorage.setItem("pref_minimize_tray", String(trayCb.checked));
      invokeTauri("set_minimize_to_tray", { enabled: state.minimizeToTray }).catch(() => {});
    }

    // Save Keep PC Awake
    const awakeCb = document.getElementById("settings-keep-awake");
    if (awakeCb) {
      state.keepPcAwake = awakeCb.checked;
      localStorage.setItem("pref_keep_awake", String(awakeCb.checked));
      invokeTauri("set_keep_pc_awake", { active: state.keepPcAwake }).catch(() => {});
    }

    // Save Restart on Complete
    const restartCb = document.getElementById("settings-restart-complete");
    if (restartCb) {
      state.restartOnComplete = restartCb.checked;
      localStorage.setItem("pref_restart_complete", String(restartCb.checked));
    }

    // Save Default Connections
    const connVal = parseInt(document.getElementById("settings-default-connections")?.value, 10);
    if (!isNaN(connVal)) {
      state.defaultConnections = connVal;
      localStorage.setItem("pref_default_connections", String(connVal));
    }

    // Save Global Speed Limit
    const speedInput = document.getElementById("settings-speed-limit-val");
    const speedUnit = document.getElementById("settings-speed-limit-unit")?.value || "MB";
    const speedRaw = parseFloat(speedInput?.value);
    if (!isNaN(speedRaw) && speedRaw > 0) {
      const bps = speedUnit === "MB" ? speedRaw * 1024 * 1024 : speedRaw * 1024;
      setSpeedLimit(bps);
    } else {
      setSpeedLimit(0);
    }

    closeModal("modal-settings");
  });

  document.getElementById("btn-submit-download")?.addEventListener("click", async () => {
    const errorBanner = document.getElementById("modal-error-banner");
    const errorMsg = document.getElementById("modal-error-message");
    if (errorBanner) errorBanner.style.display = "none";

    const url = document.getElementById("input-download-url").value.trim();
    if (!url) {
      if (errorMsg) errorMsg.textContent = "Please enter a valid download URL.";
      if (errorBanner) errorBanner.style.display = "flex";
      return;
    }

    const connections = parseInt(document.getElementById("select-connections").value, 10);
    const autoStart = document.getElementById("checkbox-start-immediately").checked;
    const savePath = document.getElementById("input-save-path").value.trim() || undefined;

    try {
      const task = await invokeTauri("add_download", {
        url,
        connections,
        autoStart,
        outputPath: savePath
      });

      if (task && task.id) {
        state.selectedTaskId = task.id;
      }

      closeModal("modal-add-download");
      state.lastRenderedKey = "";
      refreshTasks();
    } catch (err) {
      const errStr = typeof err === "string" ? err : (err.message || "Failed to start download");
      if (errorMsg) errorMsg.textContent = errStr;
      if (errorBanner) errorBanner.style.display = "flex";
    }
  });
}

// Modal Helpers
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("open");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("open");
}

async function openAddModal() {
  openModal("modal-add-download");
  const banner = document.getElementById("modal-error-banner");
  if (banner) banner.style.display = "none";

  const defaultConn = state.defaultConnections || 16;
  const hiddenConn = document.getElementById("select-connections");
  if (hiddenConn) hiddenConn.value = String(defaultConn);
  const labelConn = document.getElementById("label-add-streams");
  if (labelConn) labelConn.textContent = `${defaultConn} Streams${defaultConn === 16 ? " (Recommended)" : ""}`;
  const menu = document.getElementById("menu-add-streams");
  if (menu) {
    menu.querySelectorAll(".custom-select-item").forEach(item => {
      if (item.dataset.value === String(defaultConn)) item.classList.add("active");
      else item.classList.remove("active");
    });
  }

  const saveInput = document.getElementById("input-save-path");
  if (saveInput && !saveInput.value && state.defaultDownloadDir) {
    saveInput.value = state.defaultDownloadDir;
  }

  try {
    const text = await navigator.clipboard.readText();
    if (text && (text.startsWith("http://") || text.startsWith("https://") || text.startsWith("magnet:"))) {
      const urlInput = document.getElementById("input-download-url");
      if (urlInput && !urlInput.value) {
        urlInput.value = text.trim();
        probeUrl(text.trim());
      }
    }
  } catch (_) {}
}

// Remote Server Inspection (Supports HTTP & Magnet links)
async function probeUrl(url) {
  const loading = document.getElementById("probe-loading");
  const details = document.getElementById("probe-details");
  const filenameEl = document.getElementById("probe-val-filename");
  const sizeEl = document.getElementById("probe-val-size");
  const rangesEl = document.getElementById("probe-val-ranges");
  const errorBanner = document.getElementById("modal-error-banner");
  const errorMsg = document.getElementById("modal-error-message");

  if (errorBanner) errorBanner.style.display = "none";
  if (loading) loading.style.display = "flex";
  if (details) details.style.display = "none";

  try {
    const probe = await invokeTauri("probe_url", { url });
    if (loading) loading.style.display = "none";
    if (details) details.style.display = "block";

    if (probe) {
      if (filenameEl) filenameEl.textContent = probe.filename || "Unknown";
      if (sizeEl) sizeEl.textContent = probe.file_size > 0 ? formatBytes(probe.file_size) : "Dynamic / Unknown Size";
      if (rangesEl) {
        if (url.startsWith("magnet:")) {
          rangesEl.textContent = "✓ BitTorrent P2P Multi-Peer";
          rangesEl.style.color = "#10b981";
        } else {
          rangesEl.textContent = probe.accepts_ranges ? "✓ Supported (RFC 7233 Multi-Stream)" : "⚠️ Single Connection";
          rangesEl.style.color = probe.accepts_ranges ? "#10b981" : "#f59e0b";
        }
      }

      if (probe.content_type && (probe.content_type.includes("text/html") || probe.content_type.includes("application/xhtml"))) {
        if (errorMsg) errorMsg.textContent = "This link points to a web page rather than a direct downloadable file.";
        if (errorBanner) errorBanner.style.display = "flex";
      }
    }
  } catch (_) {
    if (loading) loading.style.display = "none";
    if (details) details.style.display = "block";
    if (filenameEl) filenameEl.textContent = "Unable to inspect server";
    if (sizeEl) sizeEl.textContent = "—";
    if (rangesEl) rangesEl.textContent = "—";
  }
}

// Refresh Tasks List (Zero-flicker: updates DOM in-place)
async function refreshTasks() {
  try {
    const tasks = await invokeTauri("get_tasks");
    if (tasks && Array.isArray(tasks)) {
      state.tasks = tasks.filter(t => !state.pendingDeleteIds.has(t.id));
    } else {
      state.tasks = [];
    }

    updateSidebarBadges();
    renderTasksTable();
    updateSegmentInspector();
    updateGlobalMetrics();

    // Check Keep PC Awake & Restart on Complete
    const activeCount = state.tasks.filter(t => t.status === "DOWNLOADING").length;
    if (state.keepPcAwake) {
      invokeTauri("set_keep_pc_awake", { active: activeCount > 0 }).catch(() => {});
    }

    if (state.restartOnComplete && !state.hasRestarted && state.tasks.length > 0) {
      const allDone = state.tasks.every(t => t.status === "COMPLETED");
      if (allDone) {
        state.hasRestarted = true;
        invokeTauri("restart_computer").catch(() => {});
      }
    }
  } catch (err) {
    console.warn("refreshTasks warning:", err);
  }
}

// Handle Real-Time Event from Backend
function handleProgressEvent(update) {
  if (!update || !update.id) return;
  const idx = state.tasks.findIndex(t => t.id === update.id);
  if (idx !== -1) {
    state.tasks[idx] = { ...state.tasks[idx], ...update };
    updateTableRow(state.tasks[idx]);
    if (state.selectedTaskId === update.id) {
      updateSegmentInspector();
    }
    updateGlobalMetrics();
  }
}

// Filter Helper
function getFilteredTasks() {
  let filtered = state.tasks;
  if (state.activeCategory === "downloading") {
    filtered = filtered.filter(t => t.status === "DOWNLOADING");
  } else if (state.activeCategory === "completed") {
    filtered = filtered.filter(t => t.status === "COMPLETED");
  } else if (state.activeCategory === "paused") {
    filtered = filtered.filter(t => t.status === "PAUSED" || t.status === "FAILED");
  }

  if (state.searchQuery) {
    filtered = filtered.filter(t =>
      (t.filename || "").toLowerCase().includes(state.searchQuery) ||
      (t.url || "").toLowerCase().includes(state.searchQuery)
    );
  }
  return filtered;
}

// Update Badges & Counters
function updateSidebarBadges() {
  const counts = {
    all: state.tasks.length,
    downloading: 0,
    completed: 0,
    paused: 0
  };

  for (const t of state.tasks) {
    if (t.status === "DOWNLOADING") counts.downloading++;
    if (t.status === "COMPLETED") counts.completed++;
    if (t.status === "PAUSED" || t.status === "FAILED") counts.paused++;
  }

  const fAll = document.getElementById("filter-count-all");
  const fActive = document.getElementById("filter-count-active");
  const fPause = document.getElementById("filter-count-paused");

  if (fAll) fAll.textContent = counts.all;
  if (fActive) fActive.textContent = counts.downloading;
  if (fPause) fPause.textContent = counts.paused;
}

// Render Tasks Cards (Smart Reconciliation)
function renderTasksTable() {
  const container = document.getElementById("downloads-container");
  const emptyState = document.getElementById("table-empty-state");
  const filtered = getFilteredTasks();

  if (filtered.length === 0) {
    if (container) container.innerHTML = "";
    if (emptyState) emptyState.style.display = "flex";
    state.lastRenderedKey = "empty";
    return;
  }
  if (emptyState) emptyState.style.display = "none";
  if (!container) return;

  const currentKey = filtered.map(t => `${t.id}:${t.status}`).join("|") + `:${state.theme}:${state.selectedTaskId}`;

  if (state.lastRenderedKey === currentKey) {
    filtered.forEach(t => updateTableRow(t));
    return;
  }

  state.lastRenderedKey = currentKey;
  const isDark = state.theme === "dark";

  container.innerHTML = filtered.map(t => {
    const isSelected = t.id === state.selectedTaskId;
    const progressPct = t.file_size > 0 ? Math.min(100, (t.downloaded_bytes / t.file_size) * 100) : (t.status === "COMPLETED" ? 100 : 0);
    const speedStr = t.status === "DOWNLOADING" ? formatSpeed(t.speed_bps) : "—";
    const etaStr = t.status === "DOWNLOADING" ? formatTime(t.eta_seconds) : "—";

    const parts = (t.filename || "").split('.');
    let ext = parts.length > 1 ? parts.pop().toUpperCase().slice(0, 7) : (t.category || "FILE").toUpperCase().slice(0, 7);
    if (ext === "GZ" || ext === "TGZ") ext = "ARCHIVE";

    let iconName = "album";
    let iconBoxClass = isDark
      ? "bg-[#1f232c] border border-[#282d38] text-[#818cf8]"
      : "bg-[#eff6ff] border border-[#dbeafe] text-[#2563eb]";
    let badgeClass = isDark
      ? "bg-[#4f46e5]/20 text-[#a5b4fc] border border-[#4f46e5]/30"
      : "bg-[#eff6ff] text-[#2563eb] border border-[#dbeafe]";
    let progressBarClass = "progress-bar-downloading active-shimmer";

    if (t.status === "PAUSED") {
      iconName = "folder_zip";
      iconBoxClass = isDark
        ? "bg-[#1f232c] border border-[#282d38] text-amber-400"
        : "bg-[#fff7ed] border border-[#ffedd5] text-[#ea580c]";
      badgeClass = isDark
        ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
        : "bg-[#fff7ed] text-[#ea580c] border border-[#ffedd5]";
      progressBarClass = "progress-bar-paused";
    } else if (t.status === "COMPLETED") {
      iconName = "check_circle";
      iconBoxClass = isDark
        ? "bg-[#1f232c] border border-[#282d38] text-emerald-400"
        : "bg-[#ecfdf5] border border-[#a7f3d0] text-[#10b981]";
      badgeClass = isDark
        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
        : "bg-[#ecfdf5] text-[#10b981] border border-[#a7f3d0]";
      progressBarClass = "progress-bar-completed";
    } else {
      const extLower = ext.toLowerCase();
      if (["mp4", "mkv", "webm", "mov"].includes(extLower)) {
        iconName = "movie";
        iconBoxClass = isDark
          ? "bg-[#1f232c] border border-[#282d38] text-[#818cf8]"
          : "bg-[#f5f3ff] border border-[#ede9fe] text-[#7c3aed]";
        badgeClass = isDark
          ? "bg-[#4f46e5]/20 text-[#a5b4fc] border border-[#4f46e5]/30"
          : "bg-[#f5f3ff] text-[#7c3aed] border border-[#ede9fe]";
      } else if (["zip", "tar", "archive", "rar"].includes(extLower)) {
        iconName = "folder_zip";
        iconBoxClass = isDark
          ? "bg-[#1f232c] border border-[#282d38] text-amber-400"
          : "bg-[#fff7ed] border border-[#ffedd5] text-[#ea580c]";
        badgeClass = isDark
          ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
          : "bg-[#fff7ed] text-[#ea580c] border border-[#ffedd5]";
      }
    }

    let cardClasses = "";
    if (isDark) {
      cardClasses = isSelected
        ? "bg-[#1a1e27] border-[#4f46e5] ring-1 ring-[#4f46e5]/40"
        : "bg-[#161920] border-[#282d38] hover:border-[#384050]";
    } else {
      cardClasses = isSelected
        ? "bg-[#faf5ff] border-[#6366f1] ring-1 ring-[#6366f1]/25"
        : "bg-[#ffffff] border-[#e2e8f0] hover:border-[#cbd5e1]";
    }

    return `
      <article class="download-card border ${cardClasses} rounded-lg p-2.5 sm:p-3 transition-all duration-150 shadow-xs cursor-pointer select-none"
               data-id="${t.id}"
               onclick="selectTaskRow('${t.id}')">
        <div class="flex flex-col gap-1.5">
          <div class="flex items-start justify-between gap-2">

            <!-- File Icon & Details -->
            <div class="flex items-center gap-2.5 min-w-0 flex-1">
              <div class="w-8 h-8 rounded-md ${iconBoxClass} flex items-center justify-center shrink-0">
                <span class="material-symbols-outlined text-[18px]">${iconName}</span>
              </div>

              <div class="flex flex-col min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <h3 class="text-xs text-[#0f172a] dark:text-[#f3f4f6] font-semibold truncate" title="${t.filename}">${t.filename}</h3>
                  <span class="${badgeClass} px-1 py-0.2 rounded text-[9px] uppercase font-semibold shrink-0 tracking-wide">${ext}</span>
                </div>
                <span class="text-[11px] text-[#94a3b8] dark:text-[#64748b] truncate pt-0.5" title="${t.url}">${t.url}</span>
              </div>
            </div>

            <!-- Card Actions -->
            <div class="flex items-center gap-0.5 shrink-0" onclick="event.stopPropagation()">
              <button class="w-7 h-7 rounded-md hover:bg-[#f1f5f9] dark:hover:bg-[#1f232c] flex items-center justify-center text-[#64748b] dark:text-[#9ca3af] hover:text-[#0f172a] dark:hover:text-[#f3f4f6] transition-colors" title="Open Containing Folder" onclick="openFileFolder('${(t.output_path || '').replace(/\\/g, '\\\\')}')">
                <span class="material-symbols-outlined text-[15px]">folder_open</span>
              </button>
              ${t.status === 'COMPLETED' ? `
                <button class="w-7 h-7 rounded-md hover:bg-[#ecfdf5] dark:hover:bg-[#1f232c] flex items-center justify-center text-[#10b981] dark:text-[#34d399] transition-colors" onclick="openFile('${(t.output_path || '').replace(/\\/g, '\\\\')}')" title="Open File">
                  <span class="material-symbols-outlined text-[15px]">launch</span>
                </button>
              ` : t.status === 'DOWNLOADING' ? `
                <button class="w-7 h-7 rounded-md hover:bg-[#f1f5f9] dark:hover:bg-[#1f232c] flex items-center justify-center text-[#64748b] dark:text-[#9ca3af] hover:text-[#0f172a] dark:hover:text-[#f3f4f6] transition-colors" onclick="togglePause('${t.id}')" title="Pause">
                  <span class="material-symbols-outlined text-[15px]">pause</span>
                </button>
              ` : `
                <button class="w-7 h-7 rounded-md hover:bg-[#eff6ff] dark:hover:bg-[#1f232c] flex items-center justify-center text-[#2563eb] dark:text-[#818cf8] transition-colors" onclick="toggleResume('${t.id}')" title="Resume">
                  <span class="material-symbols-outlined text-[15px]">play_arrow</span>
                </button>
              `}
              <button class="w-7 h-7 rounded-md hover:bg-[#fef2f2] dark:hover:bg-[#1f232c] flex items-center justify-center text-[#64748b] dark:text-[#9ca3af] hover:text-[#ef4444] transition-colors" title="Delete Download" onclick="deleteSingleRow('${t.id}')">
                <span class="material-symbols-outlined text-[15px]">close</span>
              </button>
            </div>
          </div>

          <!-- Progress Bar Track -->
          <div class="w-full bg-[#f1f5f9] dark:bg-[#12141a] rounded-full h-1.5 overflow-hidden">
            <div class="progress-track-bar ${progressBarClass} h-full rounded-full transition-all duration-150" style="width: ${progressPct.toFixed(1)}%;"></div>
          </div>

          <!-- Telemetry Footer Row -->
          <div class="flex items-center justify-between text-xs text-[#64748b] dark:text-[#9ca3af] tabular-numbers pt-0.5">
            <div class="flex items-center gap-3">
              <span class="text-[#0f172a] dark:text-[#f3f4f6] font-medium progress-meta-bytes">
                ${formatBytes(t.downloaded_bytes)} <span class="text-[#94a3b8] dark:text-[#64748b]">/ ${formatBytes(t.file_size)}</span>
              </span>
              <span class="cell-speed ${t.status === 'DOWNLOADING' ? 'text-[#2563eb] dark:text-[#818cf8]' : 'text-[#64748b] dark:text-[#64748b]'} font-medium flex items-center gap-0.5">
                ${t.status === 'DOWNLOADING' ? `<span class="material-symbols-outlined text-[13px]">arrow_downward</span> ${speedStr}` : (t.status === 'PAUSED' ? `<span class="text-[#ea580c] dark:text-amber-400 font-medium">Paused</span>` : (t.status === 'COMPLETED' ? `<span class="text-[#10b981] dark:text-emerald-400 font-medium">Completed</span>` : `—`))}
              </span>
            </div>
            <div class="flex items-center gap-3">
              ${t.status === 'DOWNLOADING' ? `
                <span class="cell-eta text-[11px]">ETA: <span class="text-[#0f172a] dark:text-[#f3f4f6] font-medium">${etaStr}</span></span>
              ` : ''}
              <span class="progress-pct text-[#64748b] dark:text-[#9ca3af] font-medium text-[11px]">${progressPct.toFixed(0)}%</span>
            </div>
          </div>
        </div>
      </article>
    `;
  }).join("");
}

// In-Place DOM Update for Existing Card (Zero Flickering)
function updateTableRow(t) {
  const card = document.querySelector(`[data-id="${t.id}"]`);
  if (!card) return;

  const progressPct = t.file_size > 0 ? Math.min(100, (t.downloaded_bytes / t.file_size) * 100) : (t.status === "COMPLETED" ? 100 : 0);
  const fill = card.querySelector(".progress-track-bar");
  if (fill) {
    fill.style.width = `${progressPct.toFixed(1)}%`;
    if (t.status === "DOWNLOADING") {
      fill.className = "progress-track-bar progress-bar-downloading active-shimmer h-full rounded-full transition-all duration-150";
    } else if (t.status === "PAUSED") {
      fill.className = "progress-track-bar progress-bar-paused h-full rounded-full transition-all duration-150";
    } else if (t.status === "COMPLETED") {
      fill.className = "progress-track-bar progress-bar-completed h-full rounded-full transition-all duration-150";
    }
  }

  const bytesSpan = card.querySelector(".progress-meta-bytes");
  if (bytesSpan) {
    bytesSpan.innerHTML = `${formatBytes(t.downloaded_bytes)} <span class="text-[#94a3b8] dark:text-[#64748b]">/ ${formatBytes(t.file_size)}</span>`;
  }

  const pctSpan = card.querySelector(".progress-pct");
  if (pctSpan) {
    pctSpan.textContent = `${progressPct.toFixed(0)}%`;
  }

  const speedCell = card.querySelector(".cell-speed");
  if (speedCell) {
    if (t.status === "DOWNLOADING") {
      speedCell.className = "cell-speed text-[#2563eb] dark:text-[#818cf8] font-medium flex items-center gap-0.5";
      speedCell.innerHTML = `<span class="material-symbols-outlined text-[13px]">arrow_downward</span> ${formatSpeed(t.speed_bps)}`;
    } else if (t.status === "PAUSED") {
      speedCell.className = "cell-speed text-[#64748b] dark:text-[#64748b] font-medium flex items-center gap-0.5";
      speedCell.innerHTML = `<span class="text-[#ea580c] dark:text-amber-400 font-medium">Paused</span>`;
    } else if (t.status === "COMPLETED") {
      speedCell.className = "cell-speed text-[#64748b] dark:text-[#64748b] font-medium flex items-center gap-0.5";
      speedCell.innerHTML = `<span class="text-[#10b981] dark:text-emerald-400 font-medium">Completed</span>`;
    }
  }

  const etaCell = card.querySelector(".cell-eta");
  if (etaCell) {
    etaCell.innerHTML = `ETA: <span class="text-[#0f172a] dark:text-[#f3f4f6] font-medium">${t.status === "DOWNLOADING" ? formatTime(t.eta_seconds) : "—"}</span>`;
  }
}

// Window Event Handlers
window.selectTaskRow = function(id) {
  state.selectedTaskId = id;
  const isDark = state.theme === "dark";

  document.querySelectorAll(".download-card").forEach(c => {
    const isThis = c.getAttribute("data-id") === id;
    if (isThis) {
      if (isDark) {
        c.className = "download-card border bg-[#1a1e27] border-[#4f46e5] ring-1 ring-[#4f46e5]/40 rounded-lg p-2.5 sm:p-3 transition-all duration-150 shadow-xs cursor-pointer select-none";
      } else {
        c.className = "download-card border bg-[#faf5ff] border-[#6366f1] ring-1 ring-[#6366f1]/25 rounded-lg p-2.5 sm:p-3 transition-all duration-150 shadow-xs cursor-pointer select-none";
      }
    } else {
      if (isDark) {
        c.className = "download-card border bg-[#161920] border-[#282d38] hover:border-[#384050] rounded-lg p-2.5 sm:p-3 transition-all duration-150 shadow-xs cursor-pointer select-none";
      } else {
        c.className = "download-card border bg-[#ffffff] border-[#e2e8f0] hover:border-[#cbd5e1] rounded-lg p-2.5 sm:p-3 transition-all duration-150 shadow-xs cursor-pointer select-none";
      }
    }
  });

  const panel = document.getElementById("visualizer-panel");
  if (panel) {
    panel.style.display = "flex";
  }
  updateSegmentInspector();
};

window.togglePause = async function(id) {
  const t = state.tasks.find(x => x.id === id);
  if (t) {
    t.status = "PAUSED";
    t.speed_bps = 0.0;
    state.lastRenderedKey = "";
    renderTasksTable();
    updateGlobalMetrics();
    updateSidebarBadges();
  }
  try {
    await invokeTauri("pause_task", { id });
  } catch (err) {
    console.error("pause_task error:", err);
  }
  refreshTasks();
};

window.toggleResume = async function(id) {
  const t = state.tasks.find(x => x.id === id);
  if (t) {
    t.status = "DOWNLOADING";
    state.lastRenderedKey = "";
    renderTasksTable();
    updateGlobalMetrics();
    updateSidebarBadges();
  }
  try {
    await invokeTauri("resume_task", { id });
  } catch (err) {
    console.error("resume_task error:", err);
  }
  refreshTasks();
};

window.openFile = async function(path) {
  if (path) {
    try {
      await invokeTauri("open_file", { path });
    } catch (err) {
      console.error("Open file error:", err);
    }
  }
};

window.openFileFolder = async function(path) {
  if (path) {
    try {
      await invokeTauri("open_folder", { path });
    } catch (err) {
      console.error("Open folder error:", err);
    }
  }
};

window.deleteSingleRow = async function(id) {
  const task = state.tasks.find(t => t.id === id);
  const name = task ? task.filename : "this download";

  const res = await showConfirmDialog({
    title: "Delete Download",
    message: `Remove "${name}" from the queue?`,
    confirmText: "Delete",
    isDanger: true,
    showFileOption: true
  });

  if (res && res.confirmed) {
    state.pendingDeleteIds.add(id);
    setTimeout(() => state.pendingDeleteIds.delete(id), 6000);
    // Immediately remove from UI for instant zero-lag response
    state.tasks = state.tasks.filter(t => t.id !== id);
    state.checkedTaskIds.delete(id);
    if (state.selectedTaskId === id) state.selectedTaskId = null;
    state.lastRenderedKey = "";
    renderTasksTable();
    updateSidebarBadges();
    updateGlobalMetrics();

    try {
      await invokeTauri("cancel_task", { id, removeFiles: res.deleteFile });
    } catch (err) {
      console.error("cancel_task error:", err);
    }
    refreshTasks();
  }
};

// Multi-Stream Visualizer
function updateSegmentInspector() {
  const fileNameEl = document.getElementById("visualizer-filename");
  const countEl = document.getElementById("visualizer-stream-count");
  const ratioEl = document.getElementById("visualizer-ratio");
  const barFill = document.getElementById("visualizer-bar-fill");
  const grid = document.getElementById("visualizer-threads-grid");

  if (!state.selectedTaskId) {
    const active = state.tasks.find(t => t.status === "DOWNLOADING") || state.tasks[0];
    if (active) {
      state.selectedTaskId = active.id;
    } else {
      if (fileNameEl) fileNameEl.textContent = "No download selected";
      if (countEl) countEl.textContent = "0 Streams";
      if (ratioEl) ratioEl.textContent = "0 B / 0 B";
      if (barFill) barFill.innerHTML = "";
      if (grid) grid.innerHTML = "";
      return;
    }
  }

  const task = state.tasks.find(t => t.id === state.selectedTaskId);
  if (!task) return;

  if (fileNameEl) fileNameEl.textContent = task.filename;
  if (ratioEl) ratioEl.textContent = `${formatBytes(task.downloaded_bytes)} / ${formatBytes(task.file_size)}`;

  const segments = task.segments || [];
  if (countEl) countEl.textContent = `${segments.length || task.connections || 1} Streams`;

  if (!segments || segments.length === 0 || task.file_size <= 0) {
    const pct = task.file_size > 0 ? (task.downloaded_bytes / task.file_size) * 100 : (task.status === "COMPLETED" ? 100 : 0);
    if (barFill) {
      barFill.innerHTML = `
        <div class="stream-chunk" style="left: 0; width: ${pct.toFixed(1)}%; background-color: #2563eb;"></div>
      `;
    }
    if (grid) {
      grid.innerHTML = `
        <div class="thread-badge">
          <span class="thread-dot" style="background-color: #2563eb;"></span>
          <span>Stream #1: ${formatBytes(task.downloaded_bytes)} / ${formatBytes(task.file_size)}</span>
        </div>
      `;
    }
    return;
  }

  const total = task.file_size;
  if (barFill) {
    barFill.innerHTML = segments.map((seg, idx) => {
      const color = STREAM_COLORS[idx % STREAM_COLORS.length];
      const leftPct = (seg.start_byte / total) * 100;
      const widthPct = Math.max(0.5, ((seg.current_byte - seg.start_byte) / total) * 100);

      return `
        <div class="stream-chunk"
             style="left: ${leftPct.toFixed(2)}%; width: ${widthPct.toFixed(2)}%; background-color: ${color};"
             title="Stream ${idx + 1}: ${formatBytes(seg.current_byte - seg.start_byte)}">
        </div>
      `;
    }).join("");
  }

  if (grid) {
    grid.innerHTML = segments.map((seg, idx) => {
      const color = STREAM_COLORS[idx % STREAM_COLORS.length];
      const downloaded = seg.current_byte > seg.start_byte ? seg.current_byte - seg.start_byte : 0;
      const chunkTotal = seg.end_byte > seg.start_byte ? seg.end_byte - seg.start_byte + 1 : 0;
      const isDone = seg.status === "COMPLETED" || (chunkTotal > 0 && downloaded >= chunkTotal);

      return `
        <div class="thread-badge" title="Offset: ${seg.start_byte.toLocaleString()} - ${seg.end_byte.toLocaleString()}">
          <span class="thread-dot" style="background-color: ${color};"></span>
          <span>#${idx + 1}: ${formatBytes(downloaded)} ${isDone ? '✓' : ''}</span>
        </div>
      `;
    }).join("");
  }
}

// Global Metrics & Aggregate Footer
function updateGlobalMetrics() {
  const activeDownloads = state.tasks.filter(t => t.status === "DOWNLOADING");
  const pausedDownloads = state.tasks.filter(t => t.status === "PAUSED" || t.status === "FAILED");
  const totalSpeed = activeDownloads.reduce((acc, t) => acc + (t.speed_bps || 0), 0);
  const totalDownloaded = state.tasks.reduce((acc, t) => acc + (t.downloaded_bytes || 0), 0);
  const totalSize = state.tasks.reduce((acc, t) => acc + (t.file_size || 0), 0);

  const statusText = document.getElementById("titlebar-status-text");
  if (statusText) {
    if (activeDownloads.length > 0) {
      statusText.textContent = `${activeDownloads.length} active • ${formatSpeed(totalSpeed)}`;
    } else {
      statusText.textContent = "Ready";
    }
  }

  const footerSpeed = document.getElementById("footer-total-speed");
  if (footerSpeed) footerSpeed.textContent = formatSpeed(totalSpeed);

  const footerDlCount = document.getElementById("footer-count-downloading");
  if (footerDlCount) footerDlCount.textContent = activeDownloads.length;

  const footerPauseCount = document.getElementById("footer-count-paused");
  if (footerPauseCount) footerPauseCount.textContent = pausedDownloads.length;

  const footerTime = document.getElementById("footer-time-remaining");
  if (footerTime) {
    if (activeDownloads.length > 0 && totalSpeed > 0) {
      const remainingBytes = activeDownloads.reduce((acc, t) => acc + Math.max(0, (t.file_size || 0) - (t.downloaded_bytes || 0)), 0);
      const etaSeconds = remainingBytes / totalSpeed;
      footerTime.textContent = `Time Remaining: ~${formatTime(etaSeconds)}`;
    } else {
      footerTime.textContent = `Time Remaining: —`;
    }
  }

  const footerBytes = document.getElementById("footer-total-bytes");
  if (footerBytes) {
    footerBytes.textContent = `${formatBytes(totalDownloaded)} / ${formatBytes(totalSize)}`;
  }
}

// --- Diagnostic Logs Viewer ---
let logsPollInterval = null;
let currentLogs = [];

function openLogsModal() {
  openModal("modal-logs-dialog");
  fetchAndRenderLogs();
  if (logsPollInterval) clearInterval(logsPollInterval);
  logsPollInterval = setInterval(fetchAndRenderLogs, 1500);
}

function closeLogsModal() {
  closeModal("modal-logs-dialog");
  if (logsPollInterval) {
    clearInterval(logsPollInterval);
    logsPollInterval = null;
  }
}

async function fetchAndRenderLogs() {
  const term = document.getElementById("logs-terminal");
  if (!term) return;

  try {
    const logs = await invokeTauri("get_system_logs") || [];
    currentLogs = logs;
    renderFilteredLogs();
  } catch (e) {
    console.warn("fetch logs error:", e);
  }
}

function renderFilteredLogs() {
  const term = document.getElementById("logs-terminal");
  const stats = document.getElementById("log-stats-count");
  const search = (document.getElementById("log-search-filter")?.value || "").toLowerCase().trim();
  const level = document.getElementById("log-level-filter")?.value || "ALL";

  if (!term) return;

  let filtered = currentLogs;
  if (level === "TORRENT") {
    filtered = filtered.filter(l => l.target === "TORRENT" || l.target === "TRACKER");
  } else if (level !== "ALL") {
    filtered = filtered.filter(l => l.level === level);
  }

  if (search) {
    filtered = filtered.filter(l =>
      l.message.toLowerCase().includes(search) ||
      l.target.toLowerCase().includes(search) ||
      l.level.toLowerCase().includes(search)
    );
  }

  if (stats) {
    stats.textContent = `${filtered.length} of ${currentLogs.length} events`;
  }

  if (filtered.length === 0) {
    term.innerHTML = '<div class="text-[#64748b] italic py-2">No matching diagnostic log events recorded.</div>';
    return;
  }

  const html = filtered.map(l => {
    let lvlColor = "text-[#38bdf8]";
    if (l.level === "ERROR") lvlColor = "text-[#f87171] font-bold";
    else if (l.level === "WARN") lvlColor = "text-[#fbbf24] font-medium";
    else if (l.target === "TORRENT") lvlColor = "text-[#a78bfa] font-medium";
    else if (l.target === "TRACKER") lvlColor = "text-[#34d399] font-medium";

    const safeMsg = l.message.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<div class="py-0.5 leading-snug hover:bg-[#161a23] px-1 rounded transition-colors"><span class="text-[#64748b]">[${l.timestamp}]</span> <span class="${lvlColor}">[${l.level}]</span> <span class="text-[#818cf8]">[${l.target}]</span> <span class="text-[#e2e8f0]">${safeMsg}</span></div>`;
  }).join("");

  const wasAtBottom = (term.scrollHeight - term.scrollTop - term.clientHeight) < 60;
  term.innerHTML = html;
  if (wasAtBottom) {
    term.scrollTop = term.scrollHeight;
  }
}

async function copyDetailedLogs() {
  const btn = document.getElementById("btn-copy-logs");
  const icon = document.getElementById("copy-log-icon");
  const text = document.getElementById("copy-log-text");

  try {
    let report = "";
    try {
      report = await invokeTauri("get_diagnostic_report");
    } catch (_) {
      report = currentLogs.map(l => `[${l.timestamp}] [${l.level}] [${l.target}] ${l.message}`).join("\n");
    }

    if (!report || report.trim().length === 0) {
      report = "No diagnostic logs recorded yet.";
    }

    await navigator.clipboard.writeText(report);

    if (text) text.textContent = "Copied to Clipboard!";
    if (icon) icon.textContent = "check";
    if (btn) btn.classList.add("bg-emerald-600");

    setTimeout(() => {
      if (text) text.textContent = "Copy Detailed Log";
      if (icon) icon.textContent = "content_copy";
      if (btn) btn.classList.remove("bg-emerald-600");
    }, 2500);
  } catch (err) {
    console.error("Clipboard copy failed:", err);
  }
}

async function clearLogs() {
  try {
    await invokeTauri("clear_system_logs");
    currentLogs = [];
    renderFilteredLogs();
  } catch (err) {
    console.error("Clear logs error:", err);
  }
}

// --- Global Speed Limiter Controller ---
function initSpeedLimiter() {
  const savedLimit = parseFloat(localStorage.getItem("pref_speed_limit_bps") || "0");
  state.globalSpeedLimitBps = savedLimit;
  invokeTauri("set_speed_limit", { limitBps: savedLimit }).catch(() => {});
  updateSpeedLimiterUI();
  setupSpeedLimiterEvents();
}

function setSpeedLimit(bps) {
  const cleanBps = Math.max(0, bps);
  state.globalSpeedLimitBps = cleanBps;
  localStorage.setItem("pref_speed_limit_bps", String(cleanBps));
  invokeTauri("set_speed_limit", { limitBps: cleanBps }).catch(() => {});
  updateSpeedLimiterUI();
}

function updateSpeedLimiterUI() {
  const bps = state.globalSpeedLimitBps || 0;
  const label = document.getElementById("speed-limiter-label");
  const badge = document.getElementById("speed-limiter-badge");
  const icon = document.getElementById("speed-limiter-icon");
  const footerText = document.getElementById("footer-limiter-text");
  const footerPill = document.getElementById("footer-speed-limiter-pill");
  const slider = document.getElementById("speed-limiter-slider");
  const sliderLabel = document.getElementById("speed-slider-label");
  const input = document.getElementById("speed-limiter-input");
  const unit = document.getElementById("speed-limiter-unit");

  const formattedStr = bps > 0 ? formatSpeed(bps) : "Unlimited";
  const displayLabel = bps > 0 ? formattedStr : "Unlimited";

  if (label) label.textContent = displayLabel;
  if (footerText) footerText.textContent = bps > 0 ? `Limit: ${displayLabel}` : "Unlimited";

  if (bps > 0) {
    if (badge) {
      badge.textContent = "Active";
      badge.className = "px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-amber-500/10 text-amber-500 border border-amber-500/20";
    }
    if (icon) icon.className = "material-symbols-outlined text-[15px] text-amber-500";
    if (footerPill) {
      footerPill.className = "ml-1 px-1.5 py-0.5 rounded text-[10px] font-semibold border flex items-center gap-1 cursor-pointer transition-colors bg-amber-500/10 text-amber-500 border-amber-500/30 hover:border-amber-500";
    }
  } else {
    if (badge) {
      badge.textContent = "Off";
      badge.className = "px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-slate-100 dark:bg-[#1f232c] text-[#64748b] dark:text-[#9ca3af] border border-[#e2e8f0] dark:border-[#282d38]";
    }
    if (icon) icon.className = "material-symbols-outlined text-[15px] text-[#2563eb] dark:text-[#818cf8]";
    if (footerPill) {
      footerPill.className = "ml-1 px-1.5 py-0.5 rounded text-[10px] font-semibold border flex items-center gap-1 cursor-pointer transition-colors bg-slate-100 dark:bg-[#1f232c] text-[#64748b] dark:text-[#9ca3af] border-[#e2e8f0] dark:border-[#282d38] hover:border-[#6366f1]";
    }
  }

  // Update presets buttons
  document.querySelectorAll(".speed-preset-btn").forEach(btn => {
    const s = parseFloat(btn.dataset.speed || "0");
    if (Math.abs(s - bps) < 100) {
      btn.className = "speed-preset-btn active px-2 py-1.5 rounded-md text-[11px] font-medium border text-center transition-all bg-[#6366f1] text-white border-[#6366f1] dark:bg-[#4f46e5] dark:border-[#4f46e5]";
    } else {
      btn.className = "speed-preset-btn px-2 py-1.5 rounded-md text-[11px] font-medium border text-center transition-all bg-[#f8fafc] dark:bg-[#1f232c] text-[#0f172a] dark:text-[#f3f4f6] border-[#e2e8f0] dark:border-[#282d38] hover:border-[#6366f1]";
    }
  });

  // Update slider and custom input
  const mbVal = bps / (1024 * 1024);
  if (slider) slider.value = Math.min(50, Math.max(0, mbVal));
  if (sliderLabel) sliderLabel.textContent = displayLabel;

  if (input && unit) {
    if (bps === 0) {
      input.value = "";
    } else if (bps >= 1048576) {
      input.value = (bps / (1024 * 1024)).toFixed(1).replace(/\.0$/, "");
      unit.value = "MB";
    } else {
      input.value = Math.round(bps / 1024);
      unit.value = "KB";
    }
  }

  // Also update Settings modal inputs if present
  const settingsVal = document.getElementById("settings-speed-limit-val");
  const settingsUnit = document.getElementById("settings-speed-limit-unit");
  if (settingsVal && settingsUnit) {
    if (bps === 0) {
      settingsVal.value = "";
    } else if (bps >= 1048576) {
      settingsVal.value = (bps / (1024 * 1024)).toFixed(1).replace(/\.0$/, "");
      settingsUnit.value = "MB";
    } else {
      settingsVal.value = Math.round(bps / 1024);
      settingsUnit.value = "KB";
    }
  }
}

function setupSpeedLimiterEvents() {
  const triggerBtn = document.getElementById("btn-speed-limiter");
  const menu = document.getElementById("speed-limiter-menu");
  const arrow = document.getElementById("speed-limiter-arrow");
  const footerPill = document.getElementById("footer-speed-limiter-pill");

  const toggleMenu = (e) => {
    e?.stopPropagation();
    if (!menu) return;
    const isHidden = menu.classList.contains("hidden");
    // Close other dropdowns
    document.querySelectorAll(".custom-select-menu").forEach(m => m.style.display = "none");
    const destMenu = document.getElementById("quick-destination-menu");
    if (destMenu) {
      destMenu.classList.add("hidden");
      destMenu.classList.remove("flex");
    }

    if (isHidden) {
      menu.classList.remove("hidden");
      menu.classList.add("flex");
      if (arrow) arrow.style.transform = "rotate(180deg)";
    } else {
      menu.classList.add("hidden");
      menu.classList.remove("flex");
      if (arrow) arrow.style.transform = "";
    }
  };

  triggerBtn?.addEventListener("click", toggleMenu);
  footerPill?.addEventListener("click", toggleMenu);

  menu?.addEventListener("click", (e) => e.stopPropagation());

  // Preset Buttons Click
  document.querySelectorAll(".speed-preset-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const speed = parseFloat(btn.dataset.speed || "0");
      setSpeedLimit(speed);
      if (menu) {
        menu.classList.add("hidden");
        menu.classList.remove("flex");
      }
      if (arrow) arrow.style.transform = "";
    });
  });

  // Slider events
  const slider = document.getElementById("speed-limiter-slider");
  const sliderLabel = document.getElementById("speed-slider-label");
  slider?.addEventListener("input", (e) => {
    const mb = parseFloat(e.target.value) || 0;
    if (sliderLabel) {
      sliderLabel.textContent = mb === 0 ? "Unlimited" : `${mb.toFixed(1)} MB/s`;
    }
  });

  slider?.addEventListener("change", (e) => {
    const mb = parseFloat(e.target.value) || 0;
    setSpeedLimit(mb * 1024 * 1024);
  });

  // Custom Input Apply
  document.getElementById("btn-apply-custom-speed")?.addEventListener("click", (e) => {
    e.stopPropagation();
    const input = document.getElementById("speed-limiter-input");
    const unit = document.getElementById("speed-limiter-unit")?.value || "MB";
    const rawVal = parseFloat(input?.value) || 0;
    const bps = rawVal <= 0 ? 0 : (unit === "MB" ? rawVal * 1024 * 1024 : rawVal * 1024);
    setSpeedLimit(bps);
    if (menu) {
      menu.classList.add("hidden");
      menu.classList.remove("flex");
    }
    if (arrow) arrow.style.transform = "";
  });

  // Settings Modal Unlimited Button
  document.getElementById("btn-settings-unlimited")?.addEventListener("click", () => {
    const settingsVal = document.getElementById("settings-speed-limit-val");
    if (settingsVal) settingsVal.value = "";
  });
}
