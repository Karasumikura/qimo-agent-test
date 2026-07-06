const LOCAL_URL_IMPORT_ENDPOINT = "http://127.0.0.1:8000/api/imports/from-extension";
const LOCAL_UPLOAD_ENDPOINT = "http://127.0.0.1:8000/api/materials";

const el = {
  status: document.querySelector("#status"),
  courseInput: document.querySelector("#courseInput"),
  titleInput: document.querySelector("#titleInput"),
  refreshBtn: document.querySelector("#refreshBtn"),
  clearBtn: document.querySelector("#clearBtn"),
  uploadFirstBtn: document.querySelector("#uploadFirstBtn"),
  importAllBtn: document.querySelector("#importAllBtn"),
  copyBtn: document.querySelector("#copyBtn"),
  candidateList: document.querySelector("#candidateList"),
};

let currentTab = null;
let candidates = [];

function sendMessage(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

async function refresh() {
  const serviceOk = await checkLocalService();
  const state = await sendMessage({ type: "getActiveTabState" });
  currentTab = state.tab;
  candidates = (state.candidates || []).sort((a, b) => b.score - a.score || b.lastSeen - a.lastSeen);
  if (currentTab && !el.titleInput.value) {
    el.titleInput.value = currentTab.title || "course-video";
  }
  render(serviceOk);
}

async function checkLocalService() {
  try {
    const response = await fetch("http://127.0.0.1:8000/api/system", { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    return true;
  } catch {
    return false;
  }
}

function render(serviceOk = true) {
  if (!serviceOk) {
    el.status.textContent = "Local service is not connected. Start http://127.0.0.1:8000 first.";
  } else {
    el.status.textContent = currentTab
      ? `Captured ${candidates.length} candidate(s) on current tab.`
      : "No active tab found.";
  }

  if (!candidates.length) {
    el.candidateList.innerHTML = `<div class="candidate">No candidates yet. Play the video for a few seconds, then click Refresh.</div>`;
    return;
  }

  el.candidateList.innerHTML = candidates
    .slice(0, 30)
    .map((item, index) => {
      const type = [item.type, item.contentType, item.contentLength].filter(Boolean).join(" / ");
      return `
        <label class="candidate">
          <div class="candidate-head">
            <span><input type="checkbox" data-index="${index}" checked /> Candidate ${index + 1}</span>
            <span>score ${item.score}</span>
          </div>
          <div class="candidate-head">${escapeHtml(type || "media candidate")}</div>
          <div class="url">${escapeHtml(item.url)}</div>
        </label>
      `;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function selectedCandidates() {
  return [...document.querySelectorAll("[data-index]:checked")]
    .map((node) => candidates[Number(node.dataset.index)])
    .filter(Boolean);
}

async function extractTranscript() {
  if (!currentTab?.id) return "";
  try {
    const result = await chrome.scripting.executeScript({
      target: { tabId: currentTab.id },
      func: () => {
        const textNodes = [];
        const selection = String(getSelection ? getSelection() : "").trim();
        if (selection.length > 80) textNodes.push(selection);
        document
          .querySelectorAll(
            "textarea,[contenteditable=true],.transcript,.subtitle,.caption,.captions,[class*=transcript],[class*=subtitle],[class*=caption],[id*=transcript],[id*=subtitle],[id*=caption]",
          )
          .forEach((node) => {
            const text = (node.value || node.innerText || node.textContent || "").trim();
            if (text.length > 80) textNodes.push(text);
          });
        document.querySelectorAll("section,article,main,div").forEach((node) => {
          const text = (node.innerText || "").trim();
          if (
            text.length > 180 &&
            text.length < 30000 &&
            /(字幕|转写|转文字|文稿|00:|0:|老师|重点|考试|transcript|subtitle|caption)/i.test(text)
          ) {
            textNodes.push(text);
          }
        });
        return [...new Set(textNodes)].sort((a, b) => b.length - a.length)[0] || "";
      },
    });
    return result?.[0]?.result || "";
  } catch {
    return "";
  }
}

function titleValue() {
  return el.titleInput.value.trim() || currentTab?.title || "course-video";
}

function courseValue() {
  return el.courseInput.value.trim() || "Unnamed Course";
}

async function importSelectedUrls() {
  const serviceOk = await checkLocalService();
  if (!serviceOk) {
    el.status.textContent = "Local service is not connected.";
    return;
  }

  const selected = selectedCandidates();
  const transcript = await extractTranscript();
  if (!selected.length && !transcript) {
    el.status.textContent = "No candidate URL or transcript found.";
    return;
  }

  const urls = selected.map((item) => item.url);
  const payload = {
    course: courseValue(),
    title: titleValue(),
    url: urls[0] || "",
    page_url: currentTab?.url || "",
    kind: "lecture_video",
    auto_analyze: true,
    detected_urls: urls,
    transcript_text: transcript.slice(0, 200000),
    transcript_title: `${titleValue()}-page-transcript.txt`,
  };

  el.importAllBtn.disabled = true;
  el.status.textContent = "Submitting URL candidates...";
  try {
    const response = await fetch(LOCAL_URL_IMPORT_ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await response.text());
    el.status.textContent = `Submitted ${urls.length} URL(s), transcript ${transcript.length} chars.`;
  } catch (error) {
    el.status.textContent = `Import failed: ${error.message}`;
  } finally {
    el.importAllBtn.disabled = false;
  }
}

async function uploadFirstInBrowser() {
  const serviceOk = await checkLocalService();
  if (!serviceOk) {
    el.status.textContent = "Local service is not connected.";
    return;
  }

  const selected = selectedCandidates();
  if (!selected.length) {
    el.status.textContent = "Select at least one candidate.";
    return;
  }

  el.uploadFirstBtn.disabled = true;
  el.status.textContent = "Downloading with browser session...";
  try {
    const item = selected[0];
    const response = await fetch(item.url, {
      credentials: "include",
      cache: "no-store",
      referrer: currentTab?.url || undefined,
    });
    if (!response.ok) throw new Error(`media HTTP ${response.status}`);

    const blob = await response.blob();
    if (!blob.size) throw new Error("empty media response");
    if ((blob.type || "").includes("text/html")) throw new Error("got HTML instead of media");

    const form = new FormData();
    const suffix = suffixFromCandidate(item, blob);
    form.append("course", courseValue());
    form.append("kind", "lecture_video");
    form.append("file", blob, `${sanitizeFilename(titleValue())}${suffix}`);

    const upload = await fetch(LOCAL_UPLOAD_ENDPOINT, {
      method: "POST",
      body: form,
    });
    if (!upload.ok) throw new Error(await upload.text());
    el.status.textContent = `Uploaded ${Math.round(blob.size / 1024 / 1024)} MB through browser session.`;
  } catch (error) {
    el.status.textContent = `Browser upload failed: ${error.message}. Try Import URLs.`;
  } finally {
    el.uploadFirstBtn.disabled = false;
  }
}

function suffixFromCandidate(item, blob) {
  const url = item.url || "";
  const match = url.match(/\.(mp4|m3u8|webm|mov|mkv|flv|m4a|mp3|wav)(?:[?#]|$)/i);
  if (match) return `.${match[1].toLowerCase()}`;
  const type = blob.type || item.contentType || "";
  if (type.includes("mpegurl")) return ".m3u8";
  if (type.includes("webm")) return ".webm";
  if (type.includes("quicktime")) return ".mov";
  if (type.includes("audio/mpeg")) return ".mp3";
  if (type.includes("audio/")) return ".m4a";
  return ".mp4";
}

function sanitizeFilename(value) {
  return String(value || "course-video").replace(/[\\/:*?"<>|]+/g, "_").slice(0, 90);
}

async function copyCandidates() {
  const urls = selectedCandidates().map((item) => item.url).join("\n");
  await navigator.clipboard.writeText(urls);
  el.status.textContent = `Copied ${selectedCandidates().length} candidate(s).`;
}

async function clearActiveTab() {
  await sendMessage({ type: "clearActiveTab" });
  await refresh();
}

el.refreshBtn.addEventListener("click", refresh);
el.clearBtn.addEventListener("click", clearActiveTab);
el.uploadFirstBtn.addEventListener("click", uploadFirstInBrowser);
el.importAllBtn.addEventListener("click", importSelectedUrls);
el.copyBtn.addEventListener("click", copyCandidates);

refresh();
