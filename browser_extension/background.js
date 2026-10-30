/**
 * IDM Modern Integration Module - Background Service Worker
 * Intercepts media streams, detects qualities, and routes downloads to desktop IDM.
 */

const DEFAULT_PORT = 9653;
const IDM_API_BASE = `http://127.0.0.1:${DEFAULT_PORT}`;

const DEFAULT_EXTENSIONS = [
  "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "dmg",
  "exe", "msi", "bat", "cmd", "apk", "bin",
  "mp4", "mkv", "webm", "avi", "mov", "flv", "m4v",
  "mp3", "wav", "flac", "aac", "ogg", "opus",
  "pdf", "epub", "docx", "xlsx", "pptx"
];

// YouTube itag metadata lookup table
const YT_ITAG_MAP = {
  18: { quality: "360p", format: "MP4", desc: "Medium Quality (Audio+Video)", order: 4 },
  22: { quality: "720p HD", format: "MP4", desc: "High Definition (Audio+Video)", order: 2 },
  137: { quality: "1080p Full HD", format: "MP4", desc: "Full HD Video", order: 1 },
  248: { quality: "1080p Full HD", format: "WebM", desc: "Full HD WebM Video", order: 1 },
  399: { quality: "1080p Full HD", format: "MP4", desc: "Full HD AV1 Video", order: 1 },
  136: { quality: "720p HD", format: "MP4", desc: "HD Video", order: 2 },
  247: { quality: "720p HD", format: "WebM", desc: "HD WebM Video", order: 2 },
  398: { quality: "720p HD", format: "MP4", desc: "HD AV1 Video", order: 2 },
  135: { quality: "480p", format: "MP4", desc: "Standard Video", order: 3 },
  244: { quality: "480p", format: "WebM", desc: "Standard WebM Video", order: 3 },
  397: { quality: "480p", format: "MP4", desc: "Standard AV1 Video", order: 3 },
  134: { quality: "360p", format: "MP4", desc: "Video", order: 4 },
  243: { quality: "360p", format: "WebM", desc: "WebM Video", order: 4 },
  396: { quality: "360p", format: "MP4", desc: "AV1 Video", order: 4 },
  140: { quality: "Audio (M4A)", format: "M4A", desc: "High Quality Audio", order: 10 },
  251: { quality: "Audio (Opus)", format: "WebM", desc: "High Quality Audio", order: 11 },
  250: { quality: "Audio (Opus)", format: "WebM", desc: "Medium Quality Audio", order: 12 },
  249: { quality: "Audio (Opus)", format: "WebM", desc: "Low Quality Audio", order: 13 }
};

// In-memory per-tab captured media streams
const tabMediaStreams = new Map();

// Initialize default storage settings
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(["interceptEnabled", "monitoredExts", "videoGrabberEnabled"], (res) => {
    if (res.interceptEnabled === undefined) {
      chrome.storage.local.set({ interceptEnabled: true });
    }
    if (!res.monitoredExts) {
      chrome.storage.local.set({ monitoredExts: DEFAULT_EXTENSIONS });
    }
    if (res.videoGrabberEnabled === undefined) {
      chrome.storage.local.set({ videoGrabberEnabled: true });
    }
  });

  // Create Context Menus
  chrome.contextMenus.create({
    id: "idm-download-link",
    title: "⚡ Download with IDM Modern",
    contexts: ["link", "video", "audio", "image"]
  });
});

// Sniff media network requests for active tabs (YouTube googlevideo, MP4, WebM, etc.)
if (chrome.webRequest && chrome.webRequest.onBeforeRequest) {
  chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
      const url = details.url;
      const tabId = details.tabId;
      if (tabId < 0) return;

      if (url.includes("googlevideo.com/videoplayback")) {
        try {
          const u = new URL(url);
          u.searchParams.delete("range");
          u.searchParams.delete("rn");
          u.searchParams.delete("rbuf");
          const cleanUrl = u.toString();

          const itag = parseInt(u.searchParams.get("itag"), 10);
          const clen = parseInt(u.searchParams.get("clen"), 10) || 0;
          const mime = u.searchParams.get("mime") || "video/mp4";

          const meta = YT_ITAG_MAP[itag] || {
            quality: itag ? `Stream #${itag}` : "Direct Stream",
            format: mime.includes("audio") ? "Audio" : "Video",
            desc: mime.split(";")[0],
            order: 5
          };

          if (!tabMediaStreams.has(tabId)) {
            tabMediaStreams.set(tabId, new Map());
          }
          const streams = tabMediaStreams.get(tabId);
          const key = `${meta.quality}_${meta.format}`;
          streams.set(key, {
            itag,
            quality: meta.quality,
            format: meta.format,
            desc: meta.desc,
            size: clen,
            url: cleanUrl,
            order: meta.order
          });
        } catch (_) {}
      } else if (
        url.match(/\.(mp4|mkv|webm|m4v|avi|mov|flv|m3u8|mp3|wav|flac|m4a|aac)(\?|$)/i) ||
        url.includes("/video/") ||
        url.includes("/media/")
      ) {
        if (!url.startsWith("blob:") && !url.startsWith("data:")) {
          if (!tabMediaStreams.has(tabId)) {
            tabMediaStreams.set(tabId, new Map());
          }
          const streams = tabMediaStreams.get(tabId);
          const extMatch = url.match(/\.([a-z0-9]{3,4})(\?|$)/i);
          const ext = extMatch ? extMatch[1].toUpperCase() : "MP4";
          const key = `stream_${ext}_${url.slice(0, 40)}`;
          if (!streams.has(key)) {
            streams.set(key, {
              quality: `${ext} Video`,
              format: ext,
              desc: "Direct Video Stream",
              size: 0,
              url: url,
              order: 5
            });
          }
        }
      }
    },
    { urls: ["<all_urls>"] }
  );
}

// Clean up tab stream cache when tabs change
chrome.tabs.onRemoved.addListener((tabId) => {
  tabMediaStreams.delete(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    tabMediaStreams.delete(tabId);
  }
});

// Handle Context Menu clicks
chrome.contextMenus.onClicked.addListener((info, tab) => {
  let targetUrl = info.linkUrl || info.srcUrl || info.pageUrl;
  if (targetUrl) {
    sendDownloadToIDM(targetUrl, tab?.url);
  }
});

// Intercept browser downloads
chrome.downloads.onCreated.addListener((downloadItem) => {
  chrome.storage.local.get(["interceptEnabled", "monitoredExts"], (res) => {
    if (!res.interceptEnabled) return;

    const exts = res.monitoredExts || DEFAULT_EXTENSIONS;
    const url = downloadItem.finalUrl || downloadItem.url;
    const cleanUrl = url.split("?")[0].split("#")[0].toLowerCase();
    const filename = (downloadItem.filename || "").toLowerCase();

    const matchesExt = exts.some(ext => cleanUrl.endsWith("." + ext) || filename.endsWith("." + ext));

    if (matchesExt) {
      chrome.downloads.cancel(downloadItem.id, () => {
        chrome.downloads.erase({ id: downloadItem.id });
      });
      sendDownloadToIDM(url, downloadItem.referrer, downloadItem.filename);
    }
  });
});

/**
 * Sends a download URL to the local IDM Desktop API server (127.0.0.1:9653).
 */
async function sendDownloadToIDM(url, referer = "", filename = "") {
  try {
    const isYt = url.includes("googlevideo.com") || (referer && referer.includes("youtube.com"));
    const finalReferer = isYt ? "https://www.youtube.com/" : (referer || "");

    const payload = {
      url: url,
      referer: finalReferer,
      filename: filename || "",
      auto_start: false
    };

    const resp = await fetch(`${IDM_API_BASE}/download`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    if (resp.ok) {
      console.log("[IDM Extension] Dispatched download to IDM Desktop:", filename || url);
    } else {
      console.warn("[IDM Extension] Desktop app returned error:", resp.status);
    }
  } catch (err) {
    console.log("[IDM Extension] Desktop app unreachable:", err);
  }
}

// Handle messages from content scripts or popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "get_detected_media") {
    const tabId = sender.tab?.id;
    const streams = (tabId && tabMediaStreams.has(tabId))
      ? Array.from(tabMediaStreams.get(tabId).values()).sort((a, b) => a.order - b.order)
      : [];
    sendResponse({ streams });
  } else if (request.action === "download_media") {
    sendDownloadToIDM(request.url, sender.tab?.url, request.filename);
    sendResponse({ status: "dispatched" });
  } else if (request.action === "resolve_youtube") {
    fetch(`${IDM_API_BASE}/resolve_youtube`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: request.url })
    })
      .then(r => r.json())
      .then(data => sendResponse(data))
      .catch(err => sendResponse({ status: "error", error: err.toString() }));
    return true;
  } else if (request.action === "check_status") {
    fetch(`${IDM_API_BASE}/status`)
      .then(r => r.json())
      .then(data => sendResponse({ online: true, data: data }))
      .catch(() => sendResponse({ online: false }));
    return true;
  }
});
