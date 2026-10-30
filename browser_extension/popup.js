/**
 * IDM Modern Popup Controller
 */

document.addEventListener("DOMContentLoaded", () => {
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  const statsDetail = document.getElementById("stats-detail");
  const interceptToggle = document.getElementById("intercept-toggle");
  const videoToggle = document.getElementById("video-toggle");
  const quickUrl = document.getElementById("quick-url");
  const quickBtn = document.getElementById("quick-btn");

  // Load preferences
  chrome.storage.local.get(["interceptEnabled", "videoGrabberEnabled"], (res) => {
    if (res.interceptEnabled !== undefined) {
      interceptToggle.checked = res.interceptEnabled;
    }
    if (res.videoGrabberEnabled !== undefined) {
      videoToggle.checked = res.videoGrabberEnabled;
    }
  });

  // Toggle handlers
  interceptToggle.addEventListener("change", () => {
    chrome.storage.local.set({ interceptEnabled: interceptToggle.checked });
  });

  videoToggle.addEventListener("change", () => {
    chrome.storage.local.set({ videoGrabberEnabled: videoToggle.checked });
  });

  // Check IDM Desktop Engine Status
  function checkEngineStatus() {
    chrome.runtime.sendMessage({ action: "check_status" }, (response) => {
      if (response && response.online) {
        statusDot.className = "dot online";
        statusText.textContent = "Engine Connected";
        const d = response.data;
        statsDetail.textContent = `${d.active_tasks || 0} active`;
      } else {
        statusDot.className = "dot offline";
        statusText.textContent = "App Not Running";
        statsDetail.textContent = "Offline";
      }
    });
  }

  checkEngineStatus();

  // Quick download submit
  quickBtn.addEventListener("click", () => {
    const url = quickUrl.value.trim();
    if (url) {
      chrome.runtime.sendMessage({
        action: "download_media",
        url: url
      }, () => {
        quickBtn.textContent = "Sent! ✔";
        setTimeout(() => {
          quickBtn.textContent = "Download";
          quickUrl.value = "";
        }, 1500);
      });
    }
  });
});

