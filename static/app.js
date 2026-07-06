const state = {
  materials: [],
  latest: null,
  refreshTimer: null,
  statusTimer: null,
  extensionPath: "D:\\QIMO_AGENT_TEST\\browser-extension\\qimo-catcher",
};

const el = {
  systemLine: document.querySelector("#systemLine"),
  refreshBtn: document.querySelector("#refreshBtn"),
  serviceState: document.querySelector("#serviceState"),
  serviceDetail: document.querySelector("#serviceDetail"),
  extensionState: document.querySelector("#extensionState"),
  extensionDetail: document.querySelector("#extensionDetail"),
  captureState: document.querySelector("#captureState"),
  captureDetail: document.querySelector("#captureDetail"),
  activityLine: document.querySelector("#activityLine"),
  courseInput: document.querySelector("#courseInput"),
  uploadForm: document.querySelector("#uploadForm"),
  kindInput: document.querySelector("#kindInput"),
  fileInput: document.querySelector("#fileInput"),
  remoteForm: document.querySelector("#remoteForm"),
  remoteTitle: document.querySelector("#remoteTitle"),
  remoteUrl: document.querySelector("#remoteUrl"),
  remotePageUrl: document.querySelector("#remotePageUrl"),
  copyExtensionPathBtn: document.querySelector("#copyExtensionPathBtn"),
  llmEnabled: document.querySelector("#llmEnabled"),
  llmBaseUrl: document.querySelector("#llmBaseUrl"),
  llmApiKey: document.querySelector("#llmApiKey"),
  llmModel: document.querySelector("#llmModel"),
  llmTemperature: document.querySelector("#llmTemperature"),
  llmStatus: document.querySelector("#llmStatus"),
  textForm: document.querySelector("#textForm"),
  textTitle: document.querySelector("#textTitle"),
  textKind: document.querySelector("#textKind"),
  textInput: document.querySelector("#textInput"),
  analyzeBtn: document.querySelector("#analyzeBtn"),
  materialCount: document.querySelector("#materialCount"),
  materialsBody: document.querySelector("#materialsBody"),
  reportMeta: document.querySelector("#reportMeta"),
  downloadReport: document.querySelector("#downloadReport"),
  warnings: document.querySelector("#warnings"),
  topicList: document.querySelector("#topicList"),
  reportPreview: document.querySelector("#reportPreview"),
  toast: document.querySelector("#toast"),
};

function toast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => {
    el.toast.hidden = true;
  }, 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function kindLabel(kind) {
  return {
    lecture_video: "课堂视频",
    lecture_audio: "课堂音频",
    imported_video: "导入视频",
    transcript: "文字稿",
    past_exam: "往年题",
    notes: "笔记",
  }[kind] || kind;
}

function statusLabel(status) {
  return {
    ready: "可分析",
    downloading: "下载中",
    processing: "处理中",
    needs_text: "待文本",
    needs_transcript: "待转写",
    error: "失败",
  }[status] || status;
}

function truncate(value, length = 72) {
  if (!value) return "";
  return value.length > length ? `${value.slice(0, length)}...` : value;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadAgentStatus() {
  const course = encodeURIComponent(el.courseInput.value.trim());
  const status = await api(`/api/agent/status${course ? `?course=${course}` : ""}`);
  state.extensionPath = status.service.extension_path || state.extensionPath;
  renderAgentStatus(status);
}

function renderAgentStatus(status) {
  const service = status.service || {};
  const extension = status.extension || {};
  const materials = status.materials || {};

  const ffmpeg = service.ffmpeg ? "ffmpeg 可用" : "ffmpeg 不可用";
  const whisper = service.whisper_installed ? "Whisper 已安装" : "Whisper 未安装";
  el.systemLine.textContent = `${ffmpeg} / ${whisper}`;
  el.serviceState.textContent = service.ok ? "运行中" : "未连接";
  el.serviceDetail.textContent = `${ffmpeg}，${whisper}`;

  if (!extension.connected || !extension.last_seen) {
    el.extensionState.textContent = "等待连接";
    el.extensionDetail.textContent = "安装扩展后打开学在吉大页面";
  } else if (!extension.auto_enabled) {
    el.extensionState.textContent = "已暂停";
    el.extensionDetail.textContent = "在扩展弹窗里打开 Auto";
  } else {
    el.extensionState.textContent = "自动模式已开启";
    el.extensionDetail.textContent = extension.page_title
      ? `最近页面：${truncate(extension.page_title, 34)}`
      : "正在等待课程视频请求";
  }

  if (extension.last_error) {
    el.captureState.textContent = "需要查看";
    el.captureDetail.textContent = truncate(extension.last_error, 56);
  } else if (materials.running) {
    el.captureState.textContent = "处理中";
    el.captureDetail.textContent = `${materials.running} 份资料正在下载或转写`;
  } else if (materials.ready) {
    el.captureState.textContent = "已有资料";
    el.captureDetail.textContent = `${materials.ready} 份可分析资料，收到 ${extension.uploaded_count || 0} 个视频上传`;
  } else {
    el.captureState.textContent = "待播放视频";
    el.captureDetail.textContent = "打开课程视频后会自动开始";
  }

  if (materials.latest) {
    el.activityLine.textContent = `最近收到：${materials.latest.original_name}，状态 ${statusLabel(materials.latest.status)}。`;
  } else if (extension.connected) {
    el.activityLine.textContent = "扩展已连接。现在打开学在吉大课程视频并播放几秒。";
  } else {
    el.activityLine.textContent = "等待扩展连接。复制扩展目录，在 Chrome 扩展页加载后再登录学在吉大。";
  }
}

async function loadMaterials() {
  const course = encodeURIComponent(el.courseInput.value.trim());
  state.materials = await api(`/api/materials${course ? `?course=${course}` : ""}`);
  renderMaterials();
}

function renderMaterials() {
  el.materialCount.textContent = `${state.materials.length} 份`;
  if (!state.materials.length) {
    el.materialsBody.innerHTML = `<tr><td colspan="5" class="empty-state">还没有资料。打开学在吉大课程视频并播放几秒，扩展会自动送入这里。</td></tr>`;
    syncAutoRefresh();
    return;
  }
  el.materialsBody.innerHTML = state.materials
    .map((item) => {
      const notes = truncate(item.notes || "");
      return `
        <tr>
          <td>${escapeHtml(item.original_name)}</td>
          <td>${kindLabel(item.kind)}</td>
          <td><span class="badge ${item.status}">${statusLabel(item.status)}</span></td>
          <td title="${escapeHtml(item.notes || "")}">${escapeHtml(notes)}</td>
          <td><button class="small-action" data-delete="${item.id}" type="button">删除</button></td>
        </tr>
      `;
    })
    .join("");
  syncAutoRefresh();
}

function currentCourse() {
  const typed = el.courseInput.value.trim();
  if (typed) return typed;
  return state.materials[0]?.course || "未命名课程";
}

async function uploadFile(event) {
  event.preventDefault();
  if (!el.fileInput.files.length) {
    toast("请选择文件");
    return;
  }
  const form = new FormData();
  form.append("course", currentCourse());
  form.append("kind", el.kindInput.value);
  form.append("file", el.fileInput.files[0]);
  el.uploadForm.querySelector("button").disabled = true;
  try {
    await api("/api/materials", { method: "POST", body: form });
    el.fileInput.value = "";
    toast("已上传，后台处理中");
    await reloadAll();
  } catch (error) {
    toast(error.message);
  } finally {
    el.uploadForm.querySelector("button").disabled = false;
  }
}

async function saveText(event) {
  event.preventDefault();
  const text = el.textInput.value.trim();
  if (!text) {
    toast("请粘贴文本");
    return;
  }
  const payload = {
    course: currentCourse(),
    kind: el.textKind.value,
    title: el.textTitle.value.trim() || "pasted-text.txt",
    text,
  };
  el.textForm.querySelector("button").disabled = true;
  try {
    await api("/api/materials/text", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    el.textInput.value = "";
    toast("文本已保存");
    await reloadAll();
  } catch (error) {
    toast(error.message);
  } finally {
    el.textForm.querySelector("button").disabled = false;
  }
}

async function importRemoteVideo(event) {
  event.preventDefault();
  const url = el.remoteUrl.value.trim();
  if (!url) {
    toast("请粘贴视频地址");
    return;
  }
  const payload = {
    course: currentCourse(),
    title: el.remoteTitle.value.trim() || "学在吉大视频",
    url,
    page_url: el.remotePageUrl.value.trim(),
    kind: "lecture_video",
    auto_analyze: true,
  };
  el.remoteForm.querySelector("button").disabled = true;
  try {
    await api("/api/imports/from-url", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    el.remoteUrl.value = "";
    toast("下载任务已创建");
    await reloadAll();
  } catch (error) {
    toast(error.message);
  } finally {
    el.remoteForm.querySelector("button").disabled = false;
  }
}

function syncAutoRefresh() {
  const hasRunningTask = state.materials.some((item) => ["downloading", "processing"].includes(item.status));
  if (hasRunningTask && !state.refreshTimer) {
    state.refreshTimer = window.setInterval(async () => {
      try {
        await reloadAll(false);
      } catch {
        window.clearInterval(state.refreshTimer);
        state.refreshTimer = null;
      }
    }, 3000);
  }
  if (!hasRunningTask && state.refreshTimer) {
    window.clearInterval(state.refreshTimer);
    state.refreshTimer = null;
  }
}

async function deleteMaterial(id) {
  await api(`/api/materials/${id}`, { method: "DELETE" });
  await reloadAll();
  toast("已删除");
}

async function analyze() {
  el.analyzeBtn.disabled = true;
  el.analyzeBtn.textContent = el.llmEnabled.checked ? "AI 分析中" : "分析中";
  try {
    const payload = {
      course: currentCourse(),
      llm: readLlmSettings(),
    };
    const result = await api("/api/analyze", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.latest = result;
    renderReport(result);
    toast("报告已生成");
  } catch (error) {
    toast(error.message);
  } finally {
    el.analyzeBtn.disabled = false;
    el.analyzeBtn.textContent = "生成报告";
  }
}

function renderReport(result) {
  const analysis = result.analysis;
  const llmText = analysis.llm?.enabled
    ? analysis.llm.status === "ok"
      ? ` / LLM ${analysis.llm.model}`
      : " / LLM 失败"
    : "";
  el.reportMeta.textContent = `${analysis.topics.length} 个知识点 / ${analysis.exam_question_count} 道往年题${llmText}`;
  el.downloadReport.href = result.report_url;
  el.downloadReport.classList.remove("disabled");
  el.reportPreview.textContent = result.report;

  if (analysis.warnings && analysis.warnings.length) {
    el.warnings.hidden = false;
    el.warnings.innerHTML = analysis.warnings.map((warning) => `<div>${escapeHtml(warning)}</div>`).join("");
  } else {
    el.warnings.hidden = true;
    el.warnings.innerHTML = "";
  }

  if (!analysis.topics.length) {
    el.topicList.className = "topic-list empty-state";
    el.topicList.textContent = "暂时没有分析结果。通常需要课堂文字稿、字幕或往年题文本。";
    return;
  }
  el.topicList.className = "topic-list";
  el.topicList.innerHTML = analysis.topics
    .slice(0, 18)
    .map((topic) => {
      const evidence = [...(topic.evidence || []), ...(topic.exam_evidence || [])]
        .slice(0, 3)
        .map((item) => `<li>${escapeHtml(item.text)}</li>`)
        .join("");
      const cues = (topic.teacher_cues || [])
        .slice(0, 5)
        .map((item) => `${item.cue} x${item.count}`)
        .join(" / ");
      return `
        <article class="topic-card">
          <header>
            <h3>${escapeHtml(topic.name)}</h3>
            <span class="badge ${topic.importance}">${topic.importance}</span>
          </header>
          <div class="topic-meta">
            <span>评分 ${topic.score}</span>
            <span>老师提示 ${topic.teacher_mentions}</span>
            <span>往年题 ${topic.exam_hits}</span>
            ${cues ? `<span>${escapeHtml(cues)}</span>` : ""}
          </div>
          <div>${escapeHtml(topic.review_action)}</div>
          ${topic.llm_reason ? `<div class="ai-note">${escapeHtml(topic.llm_reason)}</div>` : ""}
          ${topic.llm_exam_hint ? `<div class="ai-note">${escapeHtml(topic.llm_exam_hint)}</div>` : ""}
          ${evidence ? `<ol class="evidence">${evidence}</ol>` : ""}
        </article>
      `;
    })
    .join("");
}

async function loadLatest() {
  const course = encodeURIComponent(el.courseInput.value.trim());
  const latest = await api(`/api/analyses/latest${course ? `?course=${course}` : ""}`);
  if (!latest || !latest.payload) return;
  const report = await api(`/api/reports/${latest.id}.md`);
  renderReport({
    analysis: latest.payload,
    analysis_id: latest.id,
    report_url: `/api/reports/${latest.id}.md`,
    report,
  });
}

function readLlmSettings() {
  const enabled = el.llmEnabled.checked;
  return {
    enabled,
    base_url: el.llmBaseUrl.value.trim(),
    api_key: el.llmApiKey.value.trim(),
    model: el.llmModel.value.trim(),
    temperature: Number(el.llmTemperature.value || 0.2),
  };
}

function saveLlmSettings() {
  const settings = readLlmSettings();
  window.localStorage.setItem(
    "qimo_llm_settings",
    JSON.stringify({
      enabled: settings.enabled,
      base_url: settings.base_url,
      model: settings.model,
      temperature: settings.temperature,
    }),
  );
  window.sessionStorage.setItem("qimo_llm_api_key", settings.api_key);
  syncLlmStatus();
}

function loadLlmSettings() {
  try {
    const saved = JSON.parse(window.localStorage.getItem("qimo_llm_settings") || "{}");
    el.llmEnabled.checked = !!saved.enabled;
    el.llmBaseUrl.value = saved.base_url || "";
    el.llmModel.value = saved.model || "";
    el.llmTemperature.value = saved.temperature ?? "0.2";
    el.llmApiKey.value = window.sessionStorage.getItem("qimo_llm_api_key") || "";
  } catch {
    el.llmTemperature.value = "0.2";
  }
  syncLlmStatus();
}

function syncLlmStatus() {
  if (!el.llmEnabled.checked) {
    el.llmStatus.textContent = "本地规则分析";
    return;
  }
  const missing = [];
  if (!el.llmBaseUrl.value.trim()) missing.push("baseURL");
  if (!el.llmApiKey.value.trim()) missing.push("APIKEY");
  if (!el.llmModel.value.trim()) missing.push("模型");
  el.llmStatus.textContent = missing.length ? `缺少 ${missing.join("、")}` : "LLM 已配置";
}

async function copyText(text, fallbackTitle) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制");
  } catch {
    window.prompt(fallbackTitle, text);
  }
}

function copyExtensionPath() {
  copyText(state.extensionPath, "Chrome 扩展目录");
}

async function reloadAll(withLatest = true) {
  await loadAgentStatus();
  await loadMaterials();
  if (withLatest) await loadLatest();
}

async function boot() {
  try {
    loadLlmSettings();
    await reloadAll();
    state.statusTimer = window.setInterval(async () => {
      try {
        await loadAgentStatus();
      } catch {
        el.extensionState.textContent = "等待连接";
      }
    }, 5000);
  } catch (error) {
    toast(error.message);
  }
}

el.uploadForm.addEventListener("submit", uploadFile);
el.remoteForm.addEventListener("submit", importRemoteVideo);
el.textForm.addEventListener("submit", saveText);
el.copyExtensionPathBtn.addEventListener("click", copyExtensionPath);
["change", "input"].forEach((eventName) => {
  [el.llmEnabled, el.llmBaseUrl, el.llmApiKey, el.llmModel, el.llmTemperature].forEach((node) => {
    node.addEventListener(eventName, saveLlmSettings);
  });
});
el.analyzeBtn.addEventListener("click", analyze);
el.refreshBtn.addEventListener("click", async () => {
  await reloadAll();
  toast("已刷新");
});
el.courseInput.addEventListener("change", reloadAll);
el.materialsBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-delete]");
  if (!button) return;
  await deleteMaterial(button.dataset.delete);
});

boot();
