const LOCAL_BASE = "http://127.0.0.1:8000";
const LOCAL_STATUS_ENDPOINT = `${LOCAL_BASE}/api/system`;
const LOCAL_HEARTBEAT_ENDPOINT = `${LOCAL_BASE}/api/extension/heartbeat`;
const LOCAL_URL_IMPORT_ENDPOINT = `${LOCAL_BASE}/api/imports/from-extension`;
const LOCAL_UPLOAD_ENDPOINT = `${LOCAL_BASE}/api/materials`;

const MAX_CANDIDATES_PER_TAB = 120;
const AUTO_SCORE_THRESHOLD = 95;
const AUTO_DEBOUNCE_MS = 2500;
const HEARTBEAT_MS = 8000;
const IMPORTED_LIMIT = 300;
const MEDIA_EXT_PATTERN = /\.(mp4|m3u8|webm|mov|mkv|flv|m4a|mp3|vtt|srt)(\?|#|$)/i;
const DIRECT_UPLOAD_EXT_PATTERN = /\.(mp4|webm|mov|mkv|flv|m4a|mp3)(\?|#|$)/i;
const MEDIA_WORD_PATTERN = /(video|media|stream|vod|m3u8|mp4|play|courseware|resource|download|hls|dash)/i;
const TRANSCRIPT_SELECTOR =
  "textarea,[contenteditable=true],.transcript,.subtitle,.caption,.captions,[class*=transcript],[class*=subtitle],[class*=caption],[id*=transcript],[id*=subtitle],[id*=caption]";
const TRANSCRIPT_HINT_PATTERN =
  /(字幕|转写|转文字|文字稿|课程实录|识别结果|00:|0:|老师|重点|考试|transcript|subtitle|caption)/i;

const tabCandidates = new Map();
const autoTimers = new Map();
const importedUrls = new Set();
const importedTranscripts = new Set();
const state = {
  autoEnabled: true,
  serviceOk: false,
  busy: false,
  state: "starting",
  pageTitle: "",
  pageUrl: "",
  capturedCount: 0,
  submittedCount: 0,
  uploadedCount: 0,
  transcriptCount: 0,
  lastError: "",
  lastSeen: 0,
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({ autoEnabled: true });
  publishStatus("ready");
});

chrome.storage.local.get(["autoEnabled", "importedUrls"], (stored) => {
  state.autoEnabled = stored.autoEnabled !== false;
  for (const url of stored.importedUrls || []) importedUrls.add(url);
  publishStatus("ready");
});

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
  if (value.includes("application/vnd.apple.mpegurl") || value.includes("application/x-mpegurl")) return 105;
  if (value.includes("video/")) return 105;
  if (value.includes("audio/")) return 70;
  if (value.includes("octet-stream")) return 35;
  if (value.includes("text/vtt") || value.includes("application/x-subrip")) return 50;
  return 0;
}

function urlScore(url) {
  let score = 0;
  if (MEDIA_EXT_PATTERN.test(url)) score += 90;
  if (MEDIA_WORD_PATTERN.test(url)) score += 30;
  if (/[?&](token|sign|signature|auth|expires|expire|x-amz|OSSAccessKeyId)=/i.test(url)) score += 12;
  return score;
}

function typeScore(type) {
  if (type === "media") return 85;
  if (type === "xmlhttprequest" || type === "fetch") return 30;
  return 0;
}

function isLocalUrl(url) {
  return url.startsWith(LOCAL_BASE) || /^https?:\/\/(localhost|127\.0\.0\.1)(?::|\/|$)/i.test(url);
}

function shouldTrack(details, contentType = "") {
  const url = normalizeUrl(details.url);
  if (!url || isLocalUrl(url)) return false;
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
  state.capturedCount = Math.max(state.capturedCount, sorted.length);
  scheduleAutoImport(tabId);
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
  const timer = autoTimers.get(tabId);
  if (timer) clearTimeout(timer);
  autoTimers.delete(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.url && !isLocalUrl(tab.url)) {
    state.pageTitle = tab.title || state.pageTitle;
    state.pageUrl = tab.url || state.pageUrl;
    scheduleAutoImport(tabId);
  }
});

function scheduleAutoImport(tabId) {
  if (!state.autoEnabled) return;
  const existing = autoTimers.get(tabId);
  if (existing) clearTimeout(existing);
  autoTimers.set(
    tabId,
    setTimeout(() => {
      autoTimers.delete(tabId);
      autoImportTab(tabId);
    }, AUTO_DEBOUNCE_MS),
  );
}

async function autoImportTab(tabId, options = {}) {
  if (!state.autoEnabled && !options.force) return;
  if (state.busy && !options.force) return;
  const tab = await getTab(tabId);
  if (!tab || !tab.url || isLocalUrl(tab.url)) return;

  const candidates = bestCandidates(tabId);
  const transcript = await extractTranscript(tabId);
  const hasFreshTranscript = transcript && !importedTranscripts.has(hashText(`${tab.url}:${transcript.slice(0, 500)}`));
  const mediaCandidates = candidates.filter((item) => item.score >= AUTO_SCORE_THRESHOLD && !importedUrls.has(item.url));
  if (!mediaCandidates.length && !hasFreshTranscript) {
    await publishStatus("watching", tab);
    return;
  }

  state.busy = true;
  state.pageTitle = tab.title || "";
  state.pageUrl = tab.url || "";
  await publishStatus("capturing", tab);
  try {
    const uploadTarget = mediaCandidates.find(canUploadDirectly);
    if (uploadTarget) {
      await uploadMediaWithBrowserSession(uploadTarget, tab, transcript);
      rememberImported(uploadTarget.url);
      state.uploadedCount += 1;
      if (transcript) rememberTranscript(tab.url, transcript);
      state.lastError = "";
      await publishStatus("uploaded", tab);
      return;
    }

    await submitUrlCandidates(mediaCandidates, tab, transcript);
    for (const item of mediaCandidates) rememberImported(item.url);
    if (transcript) rememberTranscript(tab.url, transcript);
    state.submittedCount += mediaCandidates.length || (transcript ? 1 : 0);
    state.lastError = "";
    await publishStatus("submitted", tab);
  } catch (error) {
    state.lastError = String(error?.message || error);
    await publishStatus("error", tab);
  } finally {
    state.busy = false;
  }
}

function bestCandidates(tabId) {
  return [...(tabCandidates.get(tabId) || new Map()).values()].sort(
    (a, b) => b.score - a.score || b.lastSeen - a.lastSeen,
  );
}

function canUploadDirectly(item) {
  const contentType = String(item.contentType || "").toLowerCase();
  if (contentType.includes("application/vnd.apple.mpegurl") || contentType.includes("application/x-mpegurl")) return false;
  if (DIRECT_UPLOAD_EXT_PATTERN.test(item.url)) return true;
  return contentType.includes("video/") || contentType.includes("audio/");
}

async function uploadMediaWithBrowserSession(item, tab, transcript) {
  const response = await fetch(item.url, {
    credentials: "include",
    cache: "no-store",
    referrer: tab.url || undefined,
  });
  if (!response.ok) throw new Error(`media HTTP ${response.status}`);
  const blob = await response.blob();
  if (!blob.size) throw new Error("empty media response");
  if ((blob.type || "").includes("text/html")) throw new Error("got HTML instead of media");

  const form = new FormData();
  form.append("course", courseFromTab(tab));
  form.append("kind", "lecture_video");
  form.append("auto_analyze", "true");
  form.append("file", blob, `${sanitizeFilename(titleFromTab(tab))}${suffixFromCandidate(item, blob)}`);
  const upload = await fetch(LOCAL_UPLOAD_ENDPOINT, {
    method: "POST",
    body: form,
  });
  if (!upload.ok) throw new Error(await upload.text());

  if (transcript) {
    await submitTranscriptOnly(tab, transcript);
  }
}

async function submitUrlCandidates(candidates, tab, transcript) {
  const urls = candidates.map((item) => item.url);
  const payload = {
    course: courseFromTab(tab),
    title: titleFromTab(tab),
    url: urls[0] || "",
    page_url: tab.url || "",
    kind: "lecture_video",
    auto_analyze: true,
    detected_urls: urls,
    transcript_text: transcript ? transcript.slice(0, 200000) : "",
    transcript_title: `${sanitizeFilename(titleFromTab(tab))}-page-transcript.txt`,
  };
  const response = await fetch(LOCAL_URL_IMPORT_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await response.text());
}

async function submitTranscriptOnly(tab, transcript) {
  if (!transcript) return;
  const response = await fetch(LOCAL_URL_IMPORT_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      course: courseFromTab(tab),
      title: `${titleFromTab(tab)} page transcript`,
      page_url: tab.url || "",
      kind: "transcript",
      auto_analyze: true,
      transcript_text: transcript.slice(0, 200000),
      transcript_title: `${sanitizeFilename(titleFromTab(tab))}-page-transcript.txt`,
    }),
  });
  if (!response.ok) throw new Error(await response.text());
  state.transcriptCount += 1;
}

async function extractTranscript(tabId) {
  try {
    const result = await chrome.scripting.executeScript({
      target: { tabId },
      func: (selector, hintPatternSource) => {
        const hintPattern = new RegExp(hintPatternSource, "i");
        const textNodes = [];
        const selection = String(window.getSelection ? window.getSelection() : "").trim();
        if (selection.length > 80) textNodes.push(selection);
        document.querySelectorAll(selector).forEach((node) => {
          const text = (node.value || node.innerText || node.textContent || "").trim();
          if (text.length > 80) textNodes.push(text);
        });
        document.querySelectorAll("section,article,main,div").forEach((node) => {
          const text = (node.innerText || "").trim();
          if (text.length > 180 && text.length < 30000 && hintPattern.test(text)) {
            textNodes.push(text);
          }
        });
        return [...new Set(textNodes)].sort((a, b) => b.length - a.length)[0] || "";
      },
      args: [TRANSCRIPT_SELECTOR, TRANSCRIPT_HINT_PATTERN.source],
    });
    return result?.[0]?.result || "";
  } catch {
    return "";
  }
}

function titleFromTab(tab) {
  return (tab.title || "course-video").trim() || "course-video";
}

function courseFromTab(tab) {
  const title = titleFromTab(tab).replace(/\s*[-|_].*$/, "").trim();
  return title || "Unnamed Course";
}

function suffixFromCandidate(item, blob) {
  const url = item.url || "";
  const match = url.match(/\.(mp4|webm|mov|mkv|flv|m4a|mp3|wav)(?:[?#]|$)/i);
  if (match) return `.${match[1].toLowerCase()}`;
  const type = blob.type || item.contentType || "";
  if (type.includes("webm")) return ".webm";
  if (type.includes("quicktime")) return ".mov";
  if (type.includes("audio/mpeg")) return ".mp3";
  if (type.includes("audio/")) return ".m4a";
  return ".mp4";
}

function sanitizeFilename(value) {
  return String(value || "course-video").replace(/[\\/:*?"<>|]+/g, "_").slice(0, 90);
}

function rememberImported(url) {
  importedUrls.add(url);
  while (importedUrls.size > IMPORTED_LIMIT) {
    importedUrls.delete(importedUrls.values().next().value);
  }
  chrome.storage.local.set({ importedUrls: [...importedUrls] });
}

function rememberTranscript(pageUrl, transcript) {
  const key = hashText(`${pageUrl}:${transcript.slice(0, 500)}`);
  importedTranscripts.add(key);
}

function hashText(value) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return String(hash);
}

function getTab(tabId) {
  return new Promise((resolve) => {
    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError) resolve(null);
      else resolve(tab);
    });
  });
}

function queryActiveTab() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => resolve(tabs[0] || null));
  });
}

async function checkLocalService() {
  try {
    const response = await fetch(LOCAL_STATUS_ENDPOINT, { cache: "no-store" });
    state.serviceOk = response.ok;
    if (!response.ok) throw new Error(String(response.status));
    if (state.lastError === "Local service is offline") state.lastError = "";
    return true;
  } catch (error) {
    state.serviceOk = false;
    state.lastError = "Local service is offline";
    return false;
  }
}

async function publishStatus(nextState = state.state, tab = null) {
  if (tab) {
    state.pageTitle = tab.title || state.pageTitle;
    state.pageUrl = tab.url || state.pageUrl;
  }
  state.state = nextState;
  state.lastSeen = Date.now();
  await checkLocalService();
  updateBadge();
  try {
    await fetch(LOCAL_HEARTBEAT_ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        auto_enabled: state.autoEnabled,
        state: state.state,
        page_title: state.pageTitle,
        page_url: state.pageUrl,
        captured_count: state.capturedCount,
        submitted_count: state.submittedCount,
        uploaded_count: state.uploadedCount,
        transcript_count: state.transcriptCount,
        last_error: state.lastError,
      }),
    });
  } catch {
    updateBadge();
  }
}

function updateBadge() {
  let text = "";
  let color = "#667085";
  if (!state.autoEnabled) {
    text = "OFF";
    color = "#667085";
  } else if (!state.serviceOk) {
    text = "ERR";
    color = "#b42318";
  } else if (state.busy || state.state === "capturing") {
    text = "UP";
    color = "#a15c03";
  } else if (state.uploadedCount || state.submittedCount || state.transcriptCount) {
    text = "OK";
    color = "#0f766e";
  } else {
    text = "ON";
    color = "#2557a7";
  }
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
}

setInterval(async () => {
  const tab = await queryActiveTab();
  if (tab && tab.id != null) {
    state.pageTitle = tab.title || state.pageTitle;
    state.pageUrl = tab.url || state.pageUrl;
    state.capturedCount = bestCandidates(tab.id).length;
  }
  await publishStatus(state.state, tab);
}, HEARTBEAT_MS);

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "getStatus") {
    queryActiveTab().then((tab) => {
      const candidates = tab?.id != null ? bestCandidates(tab.id) : [];
      sendResponse({
        tab: tab
          ? {
              id: tab.id,
              title: tab.title || "",
              url: tab.url || "",
            }
          : null,
        candidates,
        status: {
          autoEnabled: state.autoEnabled,
          serviceOk: state.serviceOk,
          busy: state.busy,
          state: state.state,
          pageTitle: state.pageTitle,
          pageUrl: state.pageUrl,
          capturedCount: candidates.length,
          submittedCount: state.submittedCount,
          uploadedCount: state.uploadedCount,
          transcriptCount: state.transcriptCount,
          lastError: state.lastError,
        },
      });
    });
    return true;
  }

  if (message?.type === "setAutoEnabled") {
    state.autoEnabled = message.enabled !== false;
    chrome.storage.local.set({ autoEnabled: state.autoEnabled });
    publishStatus(state.autoEnabled ? "ready" : "paused").then(() => sendResponse({ ok: true }));
    return true;
  }

  if (message?.type === "importNow") {
    queryActiveTab().then((tab) => {
      if (!tab?.id) {
        sendResponse({ ok: false, error: "No active tab" });
        return;
      }
      autoImportTab(tab.id, { force: true })
        .then(() => sendResponse({ ok: true }))
        .catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    });
    return true;
  }

  if (message?.type === "clearHistory") {
    importedUrls.clear();
    importedTranscripts.clear();
    tabCandidates.clear();
    state.capturedCount = 0;
    state.submittedCount = 0;
    state.uploadedCount = 0;
    state.transcriptCount = 0;
    state.lastError = "";
    chrome.storage.local.set({ importedUrls: [] });
    publishStatus("ready").then(() => sendResponse({ ok: true }));
    return true;
  }

  return false;
});
