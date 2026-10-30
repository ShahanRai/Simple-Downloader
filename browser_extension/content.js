/**
 * IDM Modern Floating Video & Media Grabber
 * Detects HTML5 video players and displays IDM Download Quality Selection Menu.
 */

(function () {
  let grabberWidget = null;
  let grabberMenu = null;
  let activeVideo = null;
  let detectedStreams = [];
  let currentVideoTitle = "";

  function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return "";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    let b = bytes;
    while (b >= 1024 && i < units.length - 1) {
      b /= 1024;
      i++;
    }
    return `~${b.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  }

  function cleanTitle(title) {
    if (!title) return "video_download";
    return title
      .replace(/ - YouTube$/, "")
      .replace(/[\\/:*?"<>|]/g, "_")
      .trim();
  }

  // Create Floating Grabber Button
  function createGrabberWidget() {
    if (grabberWidget) return;

    grabberWidget = document.createElement("div");
    grabberWidget.id = "idm-video-grabber";
    grabberWidget.innerHTML = `
      <div class="idm-grabber-content">
        <span class="idm-bolt">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
          </svg>
        </span>
        <span class="idm-grabber-text">Download Video</span>
        <span class="idm-grabber-arrow">▼</span>
      </div>
    `;

    grabberWidget.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      toggleQualityMenu();
    });

    document.body.appendChild(grabberWidget);

    // Create Quality Dropdown Menu
    createQualityMenu();
  }

  // Create Quality Dropdown Menu
  function createQualityMenu() {
    if (grabberMenu) return;

    grabberMenu = document.createElement("div");
    grabberMenu.id = "idm-grabber-menu";
    grabberMenu.innerHTML = `
      <div class="idm-menu-header">
        <span class="idm-menu-title" id="idm-menu-title">Detecting video...</span>
        <span class="idm-menu-subtitle">Select Quality & Format</span>
      </div>
      <div class="idm-menu-list" id="idm-menu-list">
        <div class="idm-menu-empty">Gathering available streams...</div>
      </div>
      <div class="idm-menu-footer">
        <span>Internet Downloader</span>
        <span class="idm-menu-footer-badge">Simple Downloader</span>
      </div>
    `;

    document.body.appendChild(grabberMenu);

    // Close menu when clicking outside
    document.addEventListener("click", (e) => {
      if (!grabberWidget.contains(e.target) && !grabberMenu.contains(e.target)) {
        hideQualityMenu();
      }
    });
  }

  // Toggle Dropdown Menu
  async function toggleQualityMenu() {
    if (grabberMenu.style.display === "flex") {
      hideQualityMenu();
    } else {
      await showQualityMenu();
    }
  }

  // Extract YouTube player stream formats directly from page context
  function fetchYouTubeFormats() {
    return new Promise((resolve) => {
      const eventId = "idm_yt_fetch_" + Math.random().toString(36).substring(2);
      
      const onData = (e) => {
        window.removeEventListener(eventId, onData);
        resolve(e.detail);
      };
      window.addEventListener(eventId, onData, { once: true });

      const script = document.createElement("script");
      script.textContent = `
        (function() {
          try {
            let title = document.title;
            let formats = [];
            const pr = window.ytInitialPlayerResponse || (window.ytplayer && window.ytplayer.config && window.ytplayer.config.args && JSON.parse(window.ytplayer.config.args.raw_player_response || "{}"));
            if (pr) {
              if (pr.videoDetails && pr.videoDetails.title) {
                title = pr.videoDetails.title;
              }
              if (pr.streamingData) {
                if (pr.streamingData.formats) formats.push(...pr.streamingData.formats);
                if (pr.streamingData.adaptiveFormats) formats.push(...pr.streamingData.adaptiveFormats);
              }
            }
            window.dispatchEvent(new CustomEvent("${eventId}", {
              detail: { title, formats }
            }));
          } catch(e) {
            window.dispatchEvent(new CustomEvent("${eventId}", { detail: null }));
          }
        })();
      `;
      (document.head || document.documentElement).appendChild(script);
      script.remove();

      // Timeout fallback
      setTimeout(() => {
        window.removeEventListener(eventId, onData);
        resolve(null);
      }, 500);
    });
  }

  // Display Quality Menu
  async function showQualityMenu() {
    createGrabberWidget();
    grabberWidget.classList.add("menu-open");

    const rect = grabberWidget.getBoundingClientRect();
    grabberMenu.style.top = `${window.scrollY + rect.bottom + 6}px`;
    grabberMenu.style.left = `${window.scrollX + rect.right - 320}px`;
    grabberMenu.style.display = "flex";

    const titleEl = document.getElementById("idm-menu-title");
    const listEl = document.getElementById("idm-menu-list");

    currentVideoTitle = cleanTitle(document.title);
    titleEl.textContent = currentVideoTitle;
    listEl.innerHTML = `<div class="idm-menu-empty">Scanning formats & streams...</div>`;

    const streamsMap = new Map();

    // 1. If on YouTube, resolve stream qualities directly from Desktop IDM Bridge
    if (window.location.hostname.includes("youtube.com")) {
      try {
        const resp = await fetch("http://127.0.0.1:9653/resolve_youtube", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: window.location.href })
        });
        if (resp.ok) {
          const ytRes = await resp.json();
          if (ytRes && ytRes.status === "success" && Array.isArray(ytRes.formats) && ytRes.formats.length > 0) {
            if (ytRes.title) {
              currentVideoTitle = cleanTitle(ytRes.title);
              titleEl.textContent = currentVideoTitle;
            }
            ytRes.formats.forEach((f) => {
              const key = `${f.quality}_${f.format}`;
              streamsMap.set(key, {
                quality: f.quality,
                format: f.format,
                desc: f.is_audio ? "Audio Track" : `${f.quality} Video`,
                size: f.size,
                url: f.url,
                order: f.order,
              });
            });
          }
        }
      } catch (_) {
        try {
          const ytRes = await new Promise((r) => {
            chrome.runtime.sendMessage({ action: "resolve_youtube", url: window.location.href }, (res) => {
              if (chrome.runtime.lastError) {
                r(null);
              } else {
                r(res);
              }
            });
          });
          if (ytRes && ytRes.status === "success" && Array.isArray(ytRes.formats)) {
            ytRes.formats.forEach((f) => {
              const key = `${f.quality}_${f.format}`;
              streamsMap.set(key, {
                quality: f.quality,
                format: f.format,
                desc: f.is_audio ? "Audio Track" : `${f.quality} Video`,
                size: f.size,
                url: f.url,
                order: f.order,
              });
            });
          }
        } catch (_) {}
      }
    }

    // 2. Check Background Sniffed Media (GoogleVideo streams, MP4, WebM)
    if (streamsMap.size === 0) {
      try {
        const bgResp = await new Promise(r => {
          chrome.runtime.sendMessage({ action: "get_detected_media" }, (res) => {
            if (chrome.runtime.lastError) {
              r(null);
            } else {
              r(res);
            }
          });
        });
        if (bgResp && bgResp.streams) {
          bgResp.streams.forEach(s => {
            streamsMap.set(`${s.quality}_${s.format}`, s);
          });
        }
      } catch (_) {}
    }

    // 3. Fallback: Extract YouTube player streams from page context
    if (window.location.hostname.includes("youtube.com") && streamsMap.size === 0) {
      const ytData = await fetchYouTubeFormats();
      if (ytData) {
        if (ytData.title) {
          currentVideoTitle = cleanTitle(ytData.title);
          titleEl.textContent = currentVideoTitle;
        }

        if (ytData.formats && Array.isArray(ytData.formats)) {
          ytData.formats.forEach(f => {
            if (!f.url) return;
            const isAudioOnly = (f.mimeType || "").includes("audio") && !(f.mimeType || "").includes("video");
            const quality = f.qualityLabel || (isAudioOnly ? "Audio Track" : `${f.height || 360}p`);
            const ext = (f.mimeType || "").includes("webm") ? "WebM" : (isAudioOnly ? "M4A" : "MP4");
            const key = `${quality}_${ext}`;

            if (!streamsMap.has(key)) {
              streamsMap.set(key, {
                quality: quality,
                format: ext,
                desc: isAudioOnly ? "Audio Stream" : `${quality} Video`,
                size: parseInt(f.contentLength, 10) || 0,
                url: f.url,
                order: f.height ? -f.height : (isAudioOnly ? 999 : 500)
              });
            }
          });
        }
      }
    }

    // 4. Fallback: Check active HTML5 video tag src
    if (activeVideo && streamsMap.size === 0) {
      const src = activeVideo.currentSrc || activeVideo.src;
      if (src && !src.startsWith("blob:") && !src.startsWith("data:")) {
        const ext = src.match(/\.([a-z0-9]{3,4})(\?|$)/i)?.[1]?.toUpperCase() || "MP4";
        streamsMap.set("default", {
          quality: `${activeVideo.videoHeight ? activeVideo.videoHeight + 'p' : 'Direct'} Video`,
          format: ext,
          desc: "Full Quality Stream",
          size: 0,
          url: src,
          order: 1
        });
      }
    }

    // Render Stream Options
    const streams = Array.from(streamsMap.values()).sort((a, b) => (a.order || 0) - (b.order || 0));

    if (streams.length === 0) {
      listEl.innerHTML = `
        <div class="idm-menu-empty">
          No direct stream links detected yet.<br>
          <span style="font-size:10px; color:#64748B;">Play video for 1-2 seconds to allow stream detection.</span>
        </div>
      `;
      return;
    }

    listEl.innerHTML = streams.map(s => {
      const sizeStr = formatBytes(s.size);
      return `
        <div class="idm-menu-item" data-url="${encodeURIComponent(s.url)}" data-quality="${s.quality}" data-format="${s.format}">
          <div class="idm-item-left">
            <span class="idm-play-icon">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
              </svg>
            </span>
            <span class="idm-item-quality">${s.quality}</span>
            <span class="idm-item-format">${s.format}</span>
          </div>
          ${sizeStr ? `<span class="idm-item-size">${sizeStr}</span>` : ''}
        </div>
      `;
    }).join("");

    // Wire click handlers on quality items
    listEl.querySelectorAll(".idm-menu-item").forEach(item => {
      item.addEventListener("click", () => {
        const rawUrl = decodeURIComponent(item.getAttribute("data-url"));
        const qual = item.getAttribute("data-quality");
        const fmt = item.getAttribute("data-format").toLowerCase();
        const ext = fmt === "webm" ? "webm" : (fmt === "m4a" ? "m4a" : "mp4");
        const filename = `${currentVideoTitle} [${qual}].${ext}`;

        try {
          chrome.runtime.sendMessage({
            action: "download_media",
            url: rawUrl,
            filename: filename
          }, () => {
            if (chrome.runtime.lastError) {
              fetch("http://127.0.0.1:9653/download", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  url: rawUrl,
                  referer: "https://www.youtube.com/",
                  filename: filename,
                  auto_start: true
                })
              }).catch(() => {});
            }
          });
        } catch (_) {
          fetch("http://127.0.0.1:9653/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              url: rawUrl,
              referer: "https://www.youtube.com/",
              filename: filename,
              auto_start: true
            })
          }).catch(() => {});
        }

        hideQualityMenu();

        // Button feedback
        const textEl = grabberWidget.querySelector(".idm-grabber-text");
        if (textEl) {
          const original = textEl.textContent;
          textEl.textContent = "Sent to Simple Downloader! ✔";
          setTimeout(() => { textEl.textContent = original; }, 2500);
        }
      });
    });
  }

  function hideQualityMenu() {
    if (grabberMenu) {
      grabberMenu.style.display = "none";
    }
    if (grabberWidget) {
      grabberWidget.classList.remove("menu-open");
    }
  }

  // Attach Hover Handlers to Videos
  function attachToVideos() {
    chrome.storage.local.get(["videoGrabberEnabled"], (res) => {
      if (res.videoGrabberEnabled === false) return;

      const videos = document.querySelectorAll("video");
      videos.forEach((vid) => {
        if (vid.dataset.idmAttached) return;
        vid.dataset.idmAttached = "true";

        vid.addEventListener("mouseenter", () => {
          activeVideo = vid;
          positionGrabber(vid);
        });

        vid.addEventListener("mouseleave", () => {
          setTimeout(() => {
            if (
              grabberWidget &&
              !grabberWidget.matches(":hover") &&
              grabberMenu &&
              grabberMenu.style.display !== "flex" &&
              !vid.matches(":hover")
            ) {
              hideGrabber();
            }
          }, 400);
        });
      });
    });
  }

  // Position Grabber at Top-Right of Video
  function positionGrabber(vid) {
    createGrabberWidget();
    const rect = vid.getBoundingClientRect();
    if (rect.width < 140 || rect.height < 90) return;

    const top = window.scrollY + rect.top + 12;
    const right = window.scrollX + rect.left + rect.width - 12;

    grabberWidget.style.top = `${top}px`;
    grabberWidget.style.left = `${right - 190}px`;
    grabberWidget.style.display = "flex";
  }

  function hideGrabber() {
    if (grabberWidget && grabberMenu && grabberMenu.style.display !== "flex") {
      grabberWidget.style.display = "none";
    }
  }

  // Observe DOM for dynamic video tags
  const observer = new MutationObserver(() => {
    attachToVideos();
  });

  observer.observe(document.body || document.documentElement, {
    childList: true,
    subtree: true
  });

  // Reposition on scroll / resize
  window.addEventListener("scroll", () => {
    if (activeVideo && grabberWidget && grabberWidget.style.display === "flex") {
      positionGrabber(activeVideo);
      if (grabberMenu && grabberMenu.style.display === "flex") {
        const rect = grabberWidget.getBoundingClientRect();
        grabberMenu.style.top = `${window.scrollY + rect.bottom + 6}px`;
        grabberMenu.style.left = `${window.scrollX + rect.right - 320}px`;
      }
    }
  }, { passive: true });

  window.addEventListener("resize", () => {
    if (activeVideo && grabberWidget && grabberWidget.style.display === "flex") {
      positionGrabber(activeVideo);
    }
  }, { passive: true });

  attachToVideos();
})();
