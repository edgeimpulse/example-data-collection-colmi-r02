const state = {
  isRunning: false,
  viewMode: "live",
  selectedFile: null,
  live: {
    timestamps: [],
    accX: [],
    accY: [],
    accZ: [],
    ppg: [],
    spO2: [],
  },
};

let statusPollHandle = null;

const els = {
  statusPill: document.getElementById("status-pill"),
  messages: document.getElementById("messages"),
  patientId: document.getElementById("patientId"),
  renewPatientId: document.getElementById("renewPatientId"),
  gender: document.getElementById("gender"),
  age: document.getElementById("age"),
  country: document.getElementById("country"),
  label: document.getElementById("label"),
  duration: document.getElementById("duration"),
  resampleMs: document.getElementById("resampleMs"),
  apiKey: document.getElementById("apiKey"),
  autoUpload: document.getElementById("autoUpload"),
  scanBtn: document.getElementById("scanBtn"),
  saveDeviceBtn: document.getElementById("saveDeviceBtn"),
  deviceSelect: document.getElementById("deviceSelect"),
  startBtn: document.getElementById("startBtn"),
  stopBtn: document.getElementById("stopBtn"),
  uploadBtn: document.getElementById("uploadBtn"),
  viewerSource: document.getElementById("viewerSource"),
  refreshRawBtn: document.getElementById("refreshRawBtn"),
  rawStatus: document.getElementById("rawStatus"),
  rawTableBody: document.getElementById("rawTableBody"),
  uploadMode: document.getElementById("uploadMode"),
  accHz: document.getElementById("accHz"),
  ppgHz: document.getElementById("ppgHz"),
  spo2Hz: document.getElementById("spo2Hz"),
};

function msg(text, isError = false) {
  els.messages.textContent = text;
  els.messages.style.color = isError ? "#b42318" : "#21405f";
}

function newPatientId() {
  const c = typeof globalThis !== "undefined" ? globalThis.crypto : null;
  if (c && typeof c.randomUUID === "function") {
    return c.randomUUID();
  }

  if (c && typeof c.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    c.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
  }

  return `pid-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function setRunning(running) {
  state.isRunning = running;
  els.statusPill.textContent = running ? "Recording" : "Idle";
  els.statusPill.style.background = running ? "#e8f7ef" : "#f6f7f9";
  els.statusPill.style.color = running ? "#0f6f4a" : "#5d6573";
}

function formatHz(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return Number(value).toFixed(2);
}

function updateViewerSource(text) {
  if (els.viewerSource) {
    els.viewerSource.textContent = text;
  }
}

function setSeries(series, sourceText) {
  state.live = {
    timestamps: series.timestamps || [],
    accX: series.accX || [],
    accY: series.accY || [],
    accZ: series.accZ || [],
    ppg: series.ppg || [],
    spO2: series.spO2 || [],
  };
  redraw();
  updateViewerSource(sourceText);
}

function initCharts() {
  Plotly.newPlot(
    "accChart",
    [
      { x: [], y: [], mode: "lines+markers", name: "accX", connectgaps: true, marker: { size: 3 }, line: { color: "#0b63ce", width: 2 } },
      { x: [], y: [], mode: "lines+markers", name: "accY", connectgaps: true, marker: { size: 3 }, line: { color: "#12805c", width: 2 } },
      { x: [], y: [], mode: "lines+markers", name: "accZ", connectgaps: true, marker: { size: 3 }, line: { color: "#e35b08", width: 2 } },
    ],
    baseLayout("Accelerometer")
  );

  Plotly.newPlot(
    "spo2Chart",
    [{ x: [], y: [], mode: "lines+markers", name: "SpO2", connectgaps: true, marker: { size: 3 }, line: { color: "#ca2f4a", width: 2 } }],
    baseLayout("SpO2")
  );

  Plotly.newPlot(
    "ppgChart",
    [{ x: [], y: [], mode: "lines+markers", name: "PPG", connectgaps: true, marker: { size: 3 }, line: { color: "#6d3acf", width: 2 } }],
    baseLayout("PPG")
  );
}

function baseLayout(title) {
  return {
    title,
    margin: { l: 40, r: 20, t: 32, b: 30 },
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    font: { color: "#1b1f27" },
    xaxis: { gridcolor: "#edf0f4" },
    yaxis: { gridcolor: "#edf0f4" },
  };
}

function redraw() {
  Plotly.react(
    "accChart",
    [
      { x: state.live.timestamps, y: state.live.accX, mode: "lines+markers", name: "accX", connectgaps: true, marker: { size: 3 }, line: { color: "#0b63ce", width: 2 } },
      { x: state.live.timestamps, y: state.live.accY, mode: "lines+markers", name: "accY", connectgaps: true, marker: { size: 3 }, line: { color: "#12805c", width: 2 } },
      { x: state.live.timestamps, y: state.live.accZ, mode: "lines+markers", name: "accZ", connectgaps: true, marker: { size: 3 }, line: { color: "#e35b08", width: 2 } },
    ],
    baseLayout("Accelerometer")
  );

  Plotly.react(
    "spo2Chart",
    [{ x: state.live.timestamps, y: state.live.spO2, mode: "lines+markers", name: "SpO2", connectgaps: true, marker: { size: 3 }, line: { color: "#ca2f4a", width: 2 } }],
    baseLayout("SpO2")
  );

  Plotly.react(
    "ppgChart",
    [{ x: state.live.timestamps, y: state.live.ppg, mode: "lines+markers", name: "PPG", connectgaps: true, marker: { size: 3 }, line: { color: "#6d3acf", width: 2 } }],
    baseLayout("PPG")
  );
}

function collectPayload() {
  const option = els.deviceSelect.options[els.deviceSelect.selectedIndex];
  const selectedAddress = option ? option.value : "";
  return {
    duration: Number(els.duration.value),
    label: els.label.value.trim() || "activity",
    resample_ms: Number(els.resampleMs.value),
    selected_address: selectedAddress,
    patient_id: els.patientId.value,
    gender: els.gender.value,
    age: Number(els.age.value),
    country: els.country.value.trim(),
    auto_upload: els.autoUpload.checked,
    api_key: els.apiKey.value.trim() || null,
  };
}

async function callApi(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

async function fetchStatus() {
  const data = await callApi("/api/status");
  setRunning(data.is_running);
  if (!els.apiKey.value && data.saved_api_key) {
    els.apiKey.value = data.saved_api_key;
  }
  if (data.saved_device_address) {
    const existing = [...els.deviceSelect.options].find((o) => o.value === data.saved_device_address);
    if (!existing) {
      const opt = document.createElement("option");
      opt.value = data.saved_device_address;
      opt.textContent = `Saved device [${data.saved_device_address}]`;
      els.deviceSelect.appendChild(opt);
    }
  }
  if (state.viewMode === "live" || data.is_running) {
    state.viewMode = "live";
    setSeries(data.live, "Source: live stream");
  }
}

async function loadRawFiles() {
  const data = await callApi("/api/raw-files");
  const files = data.files || [];

  if (files.length === 0) {
    els.rawTableBody.innerHTML = "";
    els.rawStatus.textContent = "No raw datasets found in raw_data.";
    return;
  }

  els.rawStatus.textContent = `Loaded ${files.length} raw samples.`;
  els.rawTableBody.innerHTML = "";

  files.forEach((f) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${f.file_name}</td>
      <td>${f.rows ?? "-"}</td>
      <td>${formatHz(f.acc_hz)}</td>
      <td>${formatHz(f.ppg_hz)}</td>
      <td>${formatHz(f.spo2_hz)}</td>
      <td>
        <div class="actions">
          <button class="mini-btn" data-action="view" data-file="${f.file_name}">View</button>
          <button class="mini-btn primary" data-action="upload" data-file="${f.file_name}">Upload</button>
        </div>
      </td>
    `;
    els.rawTableBody.appendChild(tr);
  });
}

async function loadRawSample(fileName) {
  const data = await callApi(`/api/raw-file?file_name=${encodeURIComponent(fileName)}`);
  state.viewMode = "dataset";
  state.selectedFile = fileName;
  setSeries(data.series, `Source: dataset ${fileName}`);
  els.rawStatus.textContent = `Viewing ${fileName} (Acc ${formatHz(data.frequencies?.acc_hz)} Hz, PPG ${formatHz(data.frequencies?.ppg_hz)} Hz, SpO2 ${formatHz(data.frequencies?.spo2_hz)} Hz)`;

  if (!els.accHz.value && data.frequencies?.acc_hz) els.accHz.value = Number(data.frequencies.acc_hz).toFixed(2);
  if (!els.ppgHz.value && data.frequencies?.ppg_hz) els.ppgHz.value = Number(data.frequencies.ppg_hz).toFixed(2);
  if (!els.spo2Hz.value && data.frequencies?.spo2_hz) els.spo2Hz.value = Number(data.frequencies.spo2_hz).toFixed(2);
}

async function uploadRawSample(fileName) {
  const apiKey = els.apiKey.value.trim();
  if (!apiKey) {
    msg("Provide the Edge Impulse API key", true);
    return;
  }

  const uploadMode = els.uploadMode.value;
  const payload = {
    file_name: fileName,
    api_key: apiKey,
    label: els.label.value.trim() || "activity",
    patient_id: els.patientId.value,
    gender: els.gender.value,
    age: Number(els.age.value),
    country: els.country.value.trim(),
    upload_mode: uploadMode,
  };

  if (uploadMode === "resampled") {
    payload.acc_hz = els.accHz.value ? Number(els.accHz.value) : null;
    payload.ppg_hz = els.ppgHz.value ? Number(els.ppgHz.value) : null;
    payload.spo2_hz = els.spo2Hz.value ? Number(els.spo2Hz.value) : null;
  }

  const res = await callApi("/api/upload-file", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  msg(res.message || `Upload successful for ${fileName}`);
}

function bindRawTableActions() {
  els.rawTableBody.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-action]");
    if (!btn) return;
    const file = btn.getAttribute("data-file");
    const action = btn.getAttribute("data-action");
    if (!file) return;

    if (action === "view") {
      loadRawSample(file).catch((e) => msg(e.message, true));
    }
    if (action === "upload") {
      uploadRawSample(file).catch((e) => msg(e.message, true));
    }
  });
}

async function scanDevices() {
  msg("Scanning nearby Bluetooth devices...");
  const data = await callApi("/api/devices");
  els.deviceSelect.innerHTML = "";
  data.devices.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d.address;
    opt.textContent = `${d.name} [${d.address}]`;
    els.deviceSelect.appendChild(opt);
  });
  msg(`Found ${data.devices.length} devices`);
}

async function startRecording() {
  const payload = collectPayload();
  if (!payload.selected_address) {
    msg("Select a ring device first", true);
    return;
  }
  await callApi("/api/start", { method: "POST", body: JSON.stringify(payload) });
  setRunning(true);
  state.live = { timestamps: [], accX: [], accY: [], accZ: [], ppg: [], spO2: [] };
  redraw();
  msg("Recording started");
}

async function stopRecording() {
  await callApi("/api/stop", { method: "POST" });
  msg("Stop signal sent");
}

async function saveDevice() {
  const option = els.deviceSelect.options[els.deviceSelect.selectedIndex];
  if (!option) {
    msg("Select a device before saving", true);
    return;
  }
  const apiKey = els.apiKey.value.trim();
  await callApi("/api/device", {
    method: "POST",
    body: JSON.stringify({
      address: option.value,
      api_key: apiKey || "",
    }),
  });
  msg(apiKey ? "Device and API key saved" : "Device saved");
}

async function uploadLatest() {
  const apiKey = els.apiKey.value.trim();
  if (!apiKey) {
    msg("Provide the Edge Impulse API key", true);
    return;
  }
  const payload = {
    api_key: apiKey,
    label: els.label.value.trim() || "activity",
    patient_id: els.patientId.value,
    gender: els.gender.value,
    age: Number(els.age.value),
    country: els.country.value.trim(),
  };
  const data = await callApi("/api/upload", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  msg(data.message || "Upload successful");
}

function connectWs() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws/live`);

  ws.onmessage = (event) => {
    const evt = JSON.parse(event.data);

    if (evt.type === "snapshot") {
      setRunning(Boolean(evt.is_running));
      if (state.viewMode === "live" || evt.is_running) {
        setSeries(evt.live, "Source: live stream");
      }
      return;
    }

    if (evt.type === "data") {
      if (state.viewMode !== "live") {
        return;
      }
      state.live.timestamps.push(evt.timestamp);
      state.live.accX.push(evt.accX === "" ? null : evt.accX);
      state.live.accY.push(evt.accY === "" ? null : evt.accY);
      state.live.accZ.push(evt.accZ === "" ? null : evt.accZ);
      state.live.ppg.push(evt.ppg === "" ? null : evt.ppg);
      state.live.spO2.push(evt.spO2 === "" ? null : evt.spO2);

      const max = 1200;
      if (state.live.timestamps.length > max) {
        for (const key of Object.keys(state.live)) {
          state.live[key] = state.live[key].slice(-max);
        }
      }
      redraw();
      return;
    }

    if (evt.type === "finished") {
      setRunning(false);
      msg(evt.upload_status || "Recording completed");
      return;
    }

    if (evt.type === "error") {
      setRunning(false);
      msg(evt.message || "Recorder failed", true);
    }
  };

  ws.onclose = () => {
    msg("Live stream disconnected. Reconnecting...");
    setTimeout(connectWs, 1500);
  };
}

function startStatusPolling() {
  if (statusPollHandle) {
    clearInterval(statusPollHandle);
  }
  statusPollHandle = setInterval(() => {
    fetchStatus().catch(() => {
      // Keep UI responsive even if an occasional poll fails.
    });
  }, 1200);
}

function bindEvents() {
  els.renewPatientId.addEventListener("click", () => {
    els.patientId.value = newPatientId();
  });

  els.scanBtn.addEventListener("click", () => scanDevices().catch((e) => msg(e.message, true)));
  els.saveDeviceBtn.addEventListener("click", () => saveDevice().catch((e) => msg(e.message, true)));
  els.startBtn.addEventListener("click", () => startRecording().catch((e) => msg(e.message, true)));
  els.stopBtn.addEventListener("click", () => stopRecording().catch((e) => msg(e.message, true)));
  els.uploadBtn.addEventListener("click", () => uploadLatest().catch((e) => msg(e.message, true)));
  els.refreshRawBtn.addEventListener("click", () => loadRawFiles().catch((e) => msg(e.message, true)));

  els.uploadMode.addEventListener("change", () => {
    const enabled = els.uploadMode.value === "resampled";
    els.accHz.disabled = !enabled;
    els.ppgHz.disabled = !enabled;
    els.spo2Hz.disabled = !enabled;
  });

  bindRawTableActions();

  window.addEventListener("resize", () => {
    Plotly.Plots.resize("accChart");
    Plotly.Plots.resize("spo2Chart");
    Plotly.Plots.resize("ppgChart");
  });
}

async function init() {
  els.patientId.value = newPatientId();
  initCharts();
  bindEvents();
  connectWs();
  startStatusPolling();
  els.uploadMode.dispatchEvent(new Event("change"));
  await loadRawFiles().catch((e) => msg(e.message, true));
  await fetchStatus().catch((e) => msg(e.message, true));
}

init();
