const LOCAL_DASHBOARD = "http://127.0.0.1:8000/";

const el = {
  status: document.querySelector("#status"),
  autoToggle: document.querySelector("#autoToggle"),
  serviceMetric: document.querySelector("#serviceMetric"),
  capturedMetric: document.querySelector("#capturedMetric"),
  uploadedMetric: document.querySelector("#uploadedMetric"),
  submittedMetric: document.querySelector("#submittedMetric"),
  pageTitle: document.querySelector("#pageTitle"),
  pageUrl: document.querySelector("#pageUrl"),
  openDashboardBtn: document.querySelector("#openDashboardBtn"),
  importNowBtn: document.querySelector("#importNowBtn"),
  clearBtn: document.querySelector("#clearBtn"),
};

function sendMessage(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

async function refresh() {
  const state = await sendMessage({ type: "getStatus" });
  render(state || {});
}

function render(state) {
  const status = state.status || {};
  const tab = state.tab || {};
  el.autoToggle.checked = status.autoEnabled !== false;
  el.serviceMetric.textContent = status.serviceOk ? "Connected" : "Offline";
  el.capturedMetric.textContent = String(status.capturedCount || 0);
  el.uploadedMetric.textContent = String(status.uploadedCount || 0);
  el.submittedMetric.textContent = String(status.submittedCount || 0);
  el.pageTitle.textContent = tab.title || status.pageTitle || "No active page";
  el.pageUrl.textContent = tab.url || status.pageUrl || "";

  if (status.autoEnabled === false) {
    el.status.textContent = "Automatic import is paused.";
  } else if (!status.serviceOk) {
    el.status.textContent = "Local service is offline. Start http://127.0.0.1:8000 first.";
  } else if (status.busy || status.state === "capturing") {
    el.status.textContent = "Capturing and sending course material...";
  } else if (status.lastError && status.state === "error") {
    el.status.textContent = `Last import failed: ${status.lastError}`;
  } else {
    el.status.textContent = "Automatic capture is on.";
  }
}

async function setAutoEnabled() {
  await sendMessage({ type: "setAutoEnabled", enabled: el.autoToggle.checked });
  await refresh();
}

async function importNow() {
  el.importNowBtn.disabled = true;
  el.status.textContent = "Trying current tab now...";
  const result = await sendMessage({ type: "importNow" });
  if (result && result.ok === false) {
    el.status.textContent = result.error || "Import failed.";
  }
  el.importNowBtn.disabled = false;
  await refresh();
}

async function clearHistory() {
  el.clearBtn.disabled = true;
  await sendMessage({ type: "clearHistory" });
  el.clearBtn.disabled = false;
  await refresh();
}

function openDashboard() {
  chrome.tabs.create({ url: LOCAL_DASHBOARD });
}

el.autoToggle.addEventListener("change", setAutoEnabled);
el.importNowBtn.addEventListener("click", importNow);
el.clearBtn.addEventListener("click", clearHistory);
el.openDashboardBtn.addEventListener("click", openDashboard);

refresh();
setInterval(refresh, 2500);
