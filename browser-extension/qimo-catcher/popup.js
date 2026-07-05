const LOCAL_ENDPOINT = "http://127.0.0.1:8000/api/imports/from-extension";

const el = {
  status: document.querySelector("#status"),
  courseInput: document.querySelector("#courseInput"),
  titleInput: document.querySelector("#titleInput"),
  refreshBtn: document.querySelector("#refreshBtn"),
  clearBtn: document.querySelector("#clearBtn"),
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
  await checkLocalService();
  const state = await sendMessage({ type: "getActiveTabState" });
  currentTab = state.tab;
  candidates = (state.candidates || []).sort((a, b) => b.score - a.score || b.lastSeen - a.lastSeen);
  if (currentTab && !el.titleInput.value) {
    el.titleInput.value = currentTab.title || "学在吉大视频";
  }
  render();
}

async function checkLocalService() {
  try {
    const response = await fetch("http://127.0.0.1:8000/api/system", { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
  } catch {
    el.status.textContent = "本地服务未连接：请先启动 http://127.0.0.1:8000";
  }
}

function render() {
  el.status.textContent = currentTab
    ? `当前页捕获 ${candidates.length} 个候选`
    : "未找到当前标签页";
  if (!candidates.length) {
    el.candidateList.innerHTML = `<div class="candidate">还没有捕获到候选。请先播放视频，等待几秒后刷新。</div>`;
    return;
  }
  el.candidateList.innerHTML = candidates
    .slice(0, 30)
    .map((item, index) => {
      const type = [item.type, item.contentType, item.contentLength].filter(Boolean).join(" / ");
      return `
        <label class="candidate">
          <div class="candidate-head">
            <span><input type="checkbox" data-index="${index}" checked /> 候选 ${index + 1}</span>
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

async function importSelected() {
  await checkLocalService();
  const selected = selectedCandidates();
  const transcript = await extractTranscript();
  if (!selected.length && !transcript) {
    el.status.textContent = "没有候选 URL 或页面文字稿";
    return;
  }

  const urls = selected.map((item) => item.url);
  const payload = {
    course: el.courseInput.value.trim() || "未命名课程",
    title: el.titleInput.value.trim() || currentTab?.title || "学在吉大视频",
    url: urls[0] || "",
    page_url: currentTab?.url || "",
    kind: "lecture_video",
    auto_analyze: true,
    detected_urls: urls,
    transcript_text: transcript.slice(0, 200000),
    transcript_title: `${el.titleInput.value.trim() || "页面文字稿"}.txt`,
  };

  el.importAllBtn.disabled = true;
  el.status.textContent = "提交到本地服务";
  try {
    const response = await fetch(LOCAL_ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await response.text());
    el.status.textContent = `已提交 ${urls.length} 个候选，文字稿 ${transcript.length} 字`;
  } catch (error) {
    el.status.textContent = `导入失败：${error.message}`;
  } finally {
    el.importAllBtn.disabled = false;
  }
}

async function copyCandidates() {
  const urls = selectedCandidates().map((item) => item.url).join("\n");
  await navigator.clipboard.writeText(urls);
  el.status.textContent = `已复制 ${selectedCandidates().length} 个候选`;
}

async function clearActiveTab() {
  await sendMessage({ type: "clearActiveTab" });
  await refresh();
}

el.refreshBtn.addEventListener("click", refresh);
el.clearBtn.addEventListener("click", clearActiveTab);
el.importAllBtn.addEventListener("click", importSelected);
el.copyBtn.addEventListener("click", copyCandidates);

refresh();
