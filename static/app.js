const state = {
  materials: [],
  latest: null,
  refreshTimer: null,
};

const el = {
  systemLine: document.querySelector("#systemLine"),
  refreshBtn: document.querySelector("#refreshBtn"),
  courseInput: document.querySelector("#courseInput"),
  uploadForm: document.querySelector("#uploadForm"),
  kindInput: document.querySelector("#kindInput"),
  fileInput: document.querySelector("#fileInput"),
  remoteForm: document.querySelector("#remoteForm"),
  remoteTitle: document.querySelector("#remoteTitle"),
  remoteUrl: document.querySelector("#remoteUrl"),
  remotePageUrl: document.querySelector("#remotePageUrl"),
  copyBookmarkletBtn: document.querySelector("#copyBookmarkletBtn"),
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

async function loadSystem() {
  const system = await api("/api/system");
  const ffmpeg = system.ffmpeg ? "ffmpeg 可用" : "ffmpeg 不可用";
  const whisper = system.whisper_installed ? "Whisper 已安装" : "Whisper 未安装";
  el.systemLine.textContent = `${ffmpeg} / ${whisper}`;
}

async function loadMaterials() {
  const course = encodeURIComponent(el.courseInput.value.trim());
  state.materials = await api(`/api/materials${course ? `?course=${course}` : ""}`);
  renderMaterials();
}

function renderMaterials() {
  el.materialCount.textContent = `${state.materials.length} 份`;
  if (!state.materials.length) {
    el.materialsBody.innerHTML = `<tr><td colspan="5" class="empty-state">暂无资料</td></tr>`;
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function uploadFile(event) {
  event.preventDefault();
  if (!el.fileInput.files.length) {
    toast("请选择文件");
    return;
  }
  const form = new FormData();
  form.append("course", el.courseInput.value.trim() || "未命名课程");
  form.append("kind", el.kindInput.value);
  form.append("file", el.fileInput.files[0]);
  el.uploadForm.querySelector("button").disabled = true;
  try {
    await api("/api/materials", { method: "POST", body: form });
    el.fileInput.value = "";
    toast("上传完成");
    await loadMaterials();
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
    course: el.courseInput.value.trim() || "未命名课程",
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
    await loadMaterials();
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
    course: el.courseInput.value.trim() || "未命名课程",
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
    await loadMaterials();
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
        await loadMaterials();
      } catch (error) {
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
  await loadMaterials();
  toast("已删除");
}

async function analyze() {
  el.analyzeBtn.disabled = true;
  el.analyzeBtn.textContent = el.llmEnabled.checked ? "AI 分析中" : "分析中";
  try {
    const payload = {
      course: el.courseInput.value.trim() || "未命名课程",
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
    el.topicList.textContent = "暂无分析结果";
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

function buildBookmarklet() {
  const endpoint = `${window.location.origin}/api/imports/from-page`;
  const code = `javascript:(async()=>{const endpoint=${JSON.stringify(endpoint)};const abs=u=>{try{return new URL(u,location.href).href}catch{return''}};const add=(set,u)=>{u=abs(u||'');if(/^https?:/i.test(u))set.add(u)};const urls=new Set();document.querySelectorAll('video,source,track,a[href],link[href]').forEach(el=>{add(urls,el.currentSrc);add(urls,el.src);add(urls,el.href)});try{(performance.getEntriesByType('resource')||[]).forEach(r=>{const u=r.name||'';const t=(r.initiatorType||'').toLowerCase();const s=Number(r.transferSize||r.encodedBodySize||r.decodedBodySize||0);if(t==='video'||t==='media'||t==='fetch'||t==='xmlhttprequest'||/\\.((mp4|m3u8|m4s|ts|vtt|srt))(\\?|#|$)/i.test(u)||/(vod|video|media|stream|play|courseware|resource|download)/i.test(u)||s>500000)add(urls,u)})}catch{};try{[...document.scripts].forEach(s=>{const txt=s.textContent||'';for(const m of txt.matchAll(/https?:\\\\/\\\\/[^\\\\s'\"<>]+/g))if(/(mp4|m3u8|video|media|stream|play|vod)/i.test(m[0]))add(urls,m[0])})}catch{};const clean=[...urls].map(u=>u.replace(/&amp;/g,'&')).filter(u=>!/^blob:/i.test(u));const textNodes=[];const sel=(getSelection&&String(getSelection()).trim())||'';if(sel.length>80)textNodes.push(sel);const keys='字幕 转写 转文字 文稿 transcript subtitle captions 识别结果';document.querySelectorAll('textarea,[contenteditable=true],.transcript,.subtitle,.caption,.captions,[class*=transcript],[class*=subtitle],[class*=caption],[id*=transcript],[id*=subtitle],[id*=caption]').forEach(el=>{const txt=(el.value||el.innerText||el.textContent||'').trim();if(txt.length>80)textNodes.push(txt)});document.querySelectorAll('section,article,main,div').forEach(el=>{const txt=(el.innerText||'').trim();if(txt.length>180&&txt.length<30000&&/(字幕|转写|转文字|文稿|00:|0:|老师|重点|考试|transcript|subtitle|caption)/i.test(txt))textNodes.push(txt)});const transcript=[...new Set(textNodes)].sort((a,b)=>b.length-a.length)[0]||'';if(!clean.length&&!transcript){alert('没有检测到视频候选或页面文字稿。请先播放视频，或把浏览器扩展识别出的 mp4/m3u8 地址粘贴到本地页面。');return}const title=prompt('导入标题',document.title||'学在吉大视频');if(title===null)return;const course=prompt('课程名','未命名课程');if(course===null)return;try{const res=await fetch(endpoint,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({course,title,url:clean[0]||'',page_url:location.href,kind:'lecture_video',auto_analyze:true,detected_urls:clean,transcript_text:transcript.slice(0,200000),transcript_title:title+'-页面文字稿.txt'})});if(!res.ok)throw new Error(await res.text());alert('已提交：视频候选 '+clean.length+' 个，文字稿 '+transcript.length+' 字。回到本地页面查看进度。')}catch(err){alert('导入失败：'+err.message)}})()`;
  state.bookmarkletCode = code;
}

async function copyText(text, fallbackTitle) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制");
  } catch {
    window.prompt(fallbackTitle, text);
  }
}

function copyBookmarklet() {
  if (!state.bookmarkletCode) buildBookmarklet();
  copyText(state.bookmarkletCode, "复制这段脚本，新建书签并粘贴到网址");
}

function copyExtensionPath() {
  copyText("D:\\QIMO_AGENT_TEST\\browser-extension\\qimo-catcher", "Chrome 扩展目录");
}

async function boot() {
  try {
    loadLlmSettings();
    buildBookmarklet();
    await loadSystem();
    await loadMaterials();
    await loadLatest();
  } catch (error) {
    toast(error.message);
  }
}

el.uploadForm.addEventListener("submit", uploadFile);
el.remoteForm.addEventListener("submit", importRemoteVideo);
el.textForm.addEventListener("submit", saveText);
el.copyBookmarkletBtn.addEventListener("click", copyBookmarklet);
el.copyExtensionPathBtn.addEventListener("click", copyExtensionPath);
["change", "input"].forEach((eventName) => {
  [el.llmEnabled, el.llmBaseUrl, el.llmApiKey, el.llmModel, el.llmTemperature].forEach((node) => {
    node.addEventListener(eventName, saveLlmSettings);
  });
});
el.analyzeBtn.addEventListener("click", analyze);
el.refreshBtn.addEventListener("click", async () => {
  await loadSystem();
  await loadMaterials();
  toast("已刷新");
});
el.courseInput.addEventListener("change", loadMaterials);
el.materialsBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-delete]");
  if (!button) return;
  await deleteMaterial(button.dataset.delete);
});

boot();
