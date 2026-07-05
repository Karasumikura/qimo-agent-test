const MAX_CANDIDATES_PER_TAB = 120;
const MEDIA_EXT_PATTERN = /\.(mp4|m3u8|m4s|ts|webm|mov|mkv|flv|aac|m4a|mp3|vtt|srt)(\?|#|$)/i;
const MEDIA_WORD_PATTERN = /(video|media|stream|vod|m3u8|mp4|play|courseware|resource|download|hls|dash)/i;

const tabCandidates = new Map();

function normalizeUrl(url) {
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol)) return "";
    return parsed.href;
  } catch {
    return "";
  }
}

function getHeader(headers, name) {
  const wanted = name.toLowerCase();
  const item = (headers || []).find((header) => header.name && header.name.toLowerCase() === wanted);
  return item ? item.value || "" : "";
}

function contentTypeScore(contentType) {
  const value = String(contentType || "").toLowerCase();
  if (!value) return 0;
  if (value.includes("application/vnd.apple.mpegurl") || value.includes("application/x-mpegurl")) return 100;
  if (value.includes("video/")) return 95;
  if (value.includes("audio/")) return 55;
  if (value.includes("octet-stream")) return 30;
  if (value.includes("text/vtt") || value.includes("application/x-subrip")) return 45;
  return 0;
}

function urlScore(url) {
  let score = 0;
  if (MEDIA_EXT_PATTERN.test(url)) score += 80;
  if (MEDIA_WORD_PATTERN.test(url)) score += 30;
  if (/[?&](token|sign|signature|auth|expires|expire|x-amz|OSSAccessKeyId)=/i.test(url)) score += 12;
  return score;
}

function typeScore(type) {
  if (type === "media") return 80;
  if (type === "xmlhttprequest" || type === "fetch") return 30;
  return 0;
}

function shouldTrack(details, contentType = "") {
  const url = normalizeUrl(details.url);
  if (!url) return false;
  if (url.startsWith("http://127.0.0.1:8000/")) return false;
  return urlScore(url) + typeScore(details.type) + contentTypeScore(contentType) >= 30;
}

function addCandidate(details, extra = {}) {
  const url = normalizeUrl(details.url);
  if (!url || !shouldTrack(details, extra.contentType)) return;
  const tabId = details.tabId;
  if (tabId == null || tabId < 0) return;

  const byUrl = tabCandidates.get(tabId) || new Map();
  const existing = byUrl.get(url) || {};
  const candidate = {
    url,
    type: details.type || existing.type || "other",
    method: details.method || existing.method || "GET",
    initiator: details.initiator || details.originUrl || existing.initiator || "",
    contentType: extra.contentType || existing.contentType || "",
    contentLength: extra.contentLength || existing.contentLength || "",
    statusCode: extra.statusCode || existing.statusCode || 0,
    firstSeen: existing.firstSeen || Date.now(),
    lastSeen: Date.now(),
    score: Math.max(
      existing.score || 0,
      urlScore(url) + typeScore(details.type) + contentTypeScore(extra.contentType),
    ),
  };
  byUrl.set(url, candidate);

  const sorted = [...byUrl.entries()].sort((a, b) => b[1].score - a[1].score || b[1].lastSeen - a[1].lastSeen);
  tabCandidates.set(tabId, new Map(sorted.slice(0, MAX_CANDIDATES_PER_TAB)));
}

chrome.webRequest.onBeforeRequest.addListener(
  (details) => addCandidate(details),
  { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "other"] },
);

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    const contentType = getHeader(details.responseHeaders, "content-type");
    const contentLength = getHeader(details.responseHeaders, "content-length");
    addCandidate(details, {
      contentType,
      contentLength,
      statusCode: details.statusCode || 0,
    });
  },
  { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "other"] },
  ["responseHeaders"],
);

chrome.tabs.onRemoved.addListener((tabId) => {
  tabCandidates.delete(tabId);
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "getActiveTabState") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const tab = tabs[0];
      const candidates = tab ? [...(tabCandidates.get(tab.id) || new Map()).values()] : [];
      sendResponse({
        tab: tab
          ? {
              id: tab.id,
              title: tab.title || "",
              url: tab.url || "",
            }
          : null,
        candidates,
      });
    });
    return true;
  }

  if (message?.type === "clearActiveTab") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const tab = tabs[0];
      if (tab) tabCandidates.delete(tab.id);
      sendResponse({ ok: true });
    });
    return true;
  }

  return false;
});
