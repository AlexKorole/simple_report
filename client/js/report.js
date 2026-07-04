const urlParams = new URLSearchParams(window.location.search);
const reportId = urlParams.get("id");
let report = null;
let pollTimer = null;
let historyPollingUntil = 0;
let showLoadingPlaceholder = false;
let historySnapshot = "";
const multilistState = {}; // paramName -> { loaded, options, selected: Set }

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

async function loadMinMaxHint(p, hintEl) {
  try {
    const bounds = await api.paramOptions(reportId, p.name);
    hintEl.textContent = formatMinMaxHint(bounds);
  } catch (e) {
    // подсказка необязательна для работы формы — тихо игнорируем ошибку
  }
}

function formatMinMaxHint(bounds) {
  const parts = [];
  if (bounds && bounds.min) parts.push(`мин. ${formatDateForHint(bounds.min)}`);
  if (bounds && bounds.max) parts.push(`макс. ${formatDateForHint(bounds.max)}`);
  return parts.length ? ` (${parts.join(", ")})` : "";
}

function formatDateForHint(isoDate) {
  const [y, m, d] = String(isoDate).slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

async function init() {
  report = await api.getReport(reportId);
  document.getElementById("reportName").textContent = report.name;
  document.getElementById("reportDesc").textContent = report.description || "";
  renderParamsForm();

  document.getElementById("tabRunBtn").addEventListener("click", () => showTab("run"));
  document.getElementById("tabHistoryBtn").addEventListener("click", () => showTab("history"));
  document.getElementById("runBtn").addEventListener("click", startRun);

  showTab("run");
}

function setActiveTab(which) {
  document.getElementById("panelRun").style.display = which === "run" ? "" : "none";
  document.getElementById("panelHistory").style.display = which === "history" ? "" : "none";
  document.getElementById("tabRunBtn").className = which === "run" ? "btn" : "btn secondary";
  document.getElementById("tabHistoryBtn").className = which === "history" ? "btn" : "btn secondary";
}

function showTab(which) {
  setActiveTab(which);

  if (which === "history") {
    loadHistory();
  } else {
    historyPollingUntil = 0;
    showLoadingPlaceholder = false;
    stopPolling();
  }
}

function loadingRunRowHtml() {
  return `
    <tr>
      <td>только что</td>
      <td><span class="status running">запускается</span></td>
      <td class="muted">—</td>
      <td class="muted">—</td>
      <td></td>
    </tr>`;
}

function renderParamsForm() {
  const form = document.getElementById("paramsForm");
  form.innerHTML = "";
  for (const p of report.params || []) {
    const label = document.createElement("label");
    label.textContent = p.view_name || p.name;

    if (p.type === "multilist") {
      const field = document.createElement("div");
      field.style.cssText = "display:block; margin-bottom:12px;";

      const title = document.createElement("div");
      title.textContent = p.view_name || p.name;
      title.style.cssText = "font-weight:bold; margin-bottom:6px;";

      field.appendChild(title);
      field.appendChild(renderMultilistParam(p));
      form.appendChild(field);
      continue;
    }

    const row = document.createElement("div");
    row.style.cssText = "display:flex; gap:8px; align-items:center;";

    const input = document.createElement("input");
    input.type = p.type === "date" ? "date" : p.type === "number" ? "number" : "text";
    input.id = `param_${p.name}`;
    input.style.flex = "1";

    if (p.type === "date" && (p.min_query || p.max_query)) {
      const hint = document.createElement("span");
      hint.className = "muted";
      label.appendChild(hint);
      loadMinMaxHint(p, hint);
    }

    const allLabel = document.createElement("label");
    allLabel.style.cssText = "display:flex; align-items:center; gap:4px; margin:0; white-space:nowrap;";
    const allCheckbox = document.createElement("input");
    allCheckbox.type = "checkbox";
    allCheckbox.id = `param_${p.name}_all`;
    allCheckbox.style.cssText = "width:auto; margin:0;";
    allCheckbox.addEventListener("change", () => {
      input.disabled = allCheckbox.checked;
      if (allCheckbox.checked) input.value = "";
    });
    allLabel.appendChild(allCheckbox);
    allLabel.appendChild(document.createTextNode("Все"));

    row.appendChild(input);
    row.appendChild(allLabel);
    label.appendChild(row);
    form.appendChild(label);
  }
  if (!report.params || report.params.length === 0) {
    form.innerHTML = '<p class="muted">У этого отчёта нет параметров.</p>';
  }
}

function renderMultilistParam(p) {
  multilistState[p.name] = { loaded: false, options: [], selected: new Set() };

  const wrap = document.createElement("div");
  const row = document.createElement("div");
  row.style.cssText = "display:flex; gap:8px; align-items:center;";

  const selectBtn = document.createElement("button");
  selectBtn.type = "button";
  selectBtn.className = "btn secondary";
  selectBtn.textContent = "Выбрать (0)";

  const allLabel = document.createElement("label");
  allLabel.style.cssText = "display:flex; align-items:center; gap:4px; margin:0; white-space:nowrap;";
  const allCheckbox = document.createElement("input");
  allCheckbox.type = "checkbox";
  allCheckbox.id = `param_${p.name}_all`;
  allCheckbox.checked = true;
  allCheckbox.style.cssText = "width:auto; margin:0;";

  const panel = document.createElement("div");
  panel.className = "card";
  panel.style.cssText = "display:none; margin-top:8px;";

  allCheckbox.addEventListener("change", () => {
    if (allCheckbox.checked) {
      multilistState[p.name].selected.clear();
      selectBtn.textContent = "Выбрать (0)";
      panel.style.display = "none";
      panel.querySelectorAll(".ml-item").forEach((cb) => { cb.checked = false; });
    }
  });

  selectBtn.addEventListener("click", async () => {
    panel.style.display = "";
    if (!multilistState[p.name].loaded) {
      await loadMultilistOptions(p, panel, selectBtn, allCheckbox);
    }
  });

  allLabel.appendChild(allCheckbox);
  allLabel.appendChild(document.createTextNode("Все"));
  row.appendChild(selectBtn);
  row.appendChild(allLabel);

  wrap.appendChild(row);
  wrap.appendChild(panel);
  return wrap;
}

async function loadMultilistOptions(p, panel, selectBtn, allCheckbox) {
  panel.innerHTML = '<p class="muted">Загрузка…</p>';
  try {
    const options = await api.paramOptions(reportId, p.name);
    multilistState[p.name].options = options;
    multilistState[p.name].loaded = true;
    renderMultilistPanel(p, panel, selectBtn, allCheckbox);
  } catch (e) {
    panel.innerHTML = `<p class="error-box">${escapeHtml(e.message)}</p>`;
  }
}

function renderMultilistPanel(p, panel, selectBtn, allCheckbox) {
  const state = multilistState[p.name];
  panel.innerHTML = `
    <div style="display:flex; gap:8px; margin-bottom:8px;">
      <input type="text" placeholder="Поиск..." class="ml-search" style="flex:1" />
      <select class="ml-mode" style="width:auto">
        <option value="contains">Содержит</option>
        <option value="startswith">Начинается с</option>
      </select>
    </div>
    <div class="ml-list" style="max-height:220px; overflow-y:auto;"></div>
    <div style="display:flex; gap:8px; margin-top:8px;">
      <button type="button" class="btn secondary ml-clear">Очистить</button>
      <button type="button" class="btn secondary ml-close">Закрыть</button>
    </div>
  `;
  const searchInput = panel.querySelector(".ml-search");
  const modeSelect = panel.querySelector(".ml-mode");
  const listEl = panel.querySelector(".ml-list");

  function renderList() {
    const term = searchInput.value.trim().toLowerCase();
    const mode = modeSelect.value;
    const filtered = state.options.filter((o) => {
      if (!term) return true;
      const text = String(o.label).toLowerCase();
      return mode === "startswith" ? text.startsWith(term) : text.includes(term);
    });
    listEl.innerHTML = filtered.map((o) => {
      const checked = state.selected.has(o.value) ? "checked" : "";
      return `<div style="margin-bottom:4px;">
        <label style="display:inline-flex; align-items:flex-start; gap:6px; font-weight:normal; margin:0; max-width:100%;">
          <input type="checkbox" class="ml-item" value="${escapeHtml(String(o.value))}" ${checked} style="width:auto; margin:2px 0 0 0; flex:0 0 auto;" />
          <span>${escapeHtml(String(o.label))}</span>
        </label>
      </div>`;
    }).join("") || '<p class="muted">Ничего не найдено.</p>';

    listEl.querySelectorAll(".ml-item").forEach((cb) => {
      cb.addEventListener("change", () => {
        if (cb.checked) state.selected.add(cb.value);
        else state.selected.delete(cb.value);
        selectBtn.textContent = `Выбрать (${state.selected.size})`;
        allCheckbox.checked = state.selected.size === 0;
      });
    });
  }

  searchInput.addEventListener("input", renderList);
  modeSelect.addEventListener("change", renderList);

  panel.querySelector(".ml-clear").addEventListener("click", () => {
    state.selected.clear();
    selectBtn.textContent = "Выбрать (0)";
    allCheckbox.checked = true;
    renderList();
  });

  panel.querySelector(".ml-close").addEventListener("click", () => {
    panel.style.display = "none";
  });

  renderList();
}

function collectParams() {
  const values = {};
  for (const p of report.params || []) {
    const allChecked = document.getElementById(`param_${p.name}_all`).checked;
    if (p.type === "multilist") {
      values[p.name] = allChecked ? [] : Array.from(multilistState[p.name].selected);
      continue;
    }
    const el = document.getElementById(`param_${p.name}`);
    values[p.name] = allChecked ? "" : el.value;
  }
  return values;
}

async function startRun() {
  const runMsg = document.getElementById("runMsg");
  runMsg.textContent = "Запускаю…";

  let runsBefore = [];
  try {
    runsBefore = await api.listRuns(reportId);
  } catch {
    runsBefore = [];
  }

  historySnapshot = JSON.stringify(runsBefore.map((r) => r.file || r.ts || ""));

  historyPollingUntil = Date.now() + CLIENT_CONFIG.HISTORY_LOADING_WINDOW_MS;
  showLoadingPlaceholder = true;

  setActiveTab("history");
  renderHistory(runsBefore, true);
  startPolling();

  try {
    await api.runReport(reportId, collectParams());

    runMsg.textContent = "Готово — выгрузка запущена.";
    loadHistory();
  } catch (e) {
    historyPollingUntil = 0;
    showLoadingPlaceholder = false;
    stopPolling();

    showTab("run");
    runMsg.textContent = e.message;
  }
}

function renderHistory(runs, withLoadingRow) {
  const el = document.getElementById("historyList");

  if (runs.length === 0 && !withLoadingRow) {
    el.innerHTML = '<p class="muted">Пока нет запусков.</p>';
    return;
  }

  const loadingRow = withLoadingRow ? loadingRunRowHtml() : "";

  el.innerHTML = `
    <table>
      <thead><tr><th>Когда</th><th>Статус</th><th>Размер</th><th>Параметры</th><th></th></tr></thead>
      <tbody>${loadingRow}${runs.map(runRow).join("")}</tbody>
    </table>`;

  el.querySelectorAll("[data-delete]").forEach((btn) => {
    btn.addEventListener("click", () => onDelete(btn.dataset.delete));
  });
}

const STATUS_LABELS = {
  done: "готов",
  running: "выполняется",
  error: "ошибка",
  interrupted: "прервано (сервер перезапускали)",
};

function formatTs(ts) {
  // ts вида 20260703_215500
  const y = ts.slice(0, 4), mo = ts.slice(4, 6), d = ts.slice(6, 8);
  const h = ts.slice(9, 11), mi = ts.slice(11, 13), s = ts.slice(13, 15);
  return `${d}.${mo}.${y} ${h}:${mi}:${s}`;
}

function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function loadHistory() {
  const el = document.getElementById("historyList");

  try {
    const runs = await api.listRuns(reportId);
    const hasRunning = runs.some((r) => r.status === "running");

    const currentSnapshot = JSON.stringify(runs.map((r) => r.file || r.ts || ""));
    const historyChanged = showLoadingPlaceholder && currentSnapshot !== historySnapshot;

    if (historyChanged || hasRunning) {
      showLoadingPlaceholder = false;
      historySnapshot = currentSnapshot;
    }

    const canPollByTime = Date.now() < historyPollingUntil;
    const withLoadingRow = showLoadingPlaceholder && canPollByTime;

    renderHistory(runs, withLoadingRow);

    if (hasRunning || canPollByTime) {
      startPolling();
    } else {
      historyPollingUntil = 0;
      showLoadingPlaceholder = false;
      stopPolling();
    }
  } catch (e) {
    el.innerHTML = `<p class="error-box">${escapeHtml(e.message)}</p>`;
  }
}

function formatParamsCell(runParams) {
  if (!runParams) return '<span class="muted">—</span>';
  const cells = (report.params || []).map((p) => {
    const label = p.view_name || p.name;
    const raw = runParams[p.name];
    let valueHtml;
    if (raw === undefined || raw === null || raw === "") {
      valueHtml = "Все";
    } else if (Array.isArray(raw)) {
      valueHtml = raw.length
        ? `<div class="param-value-group">${raw.map((v) => escapeHtml(String(v))).join("<br>")}</div>`
        : "Все";
    } else {
      valueHtml = escapeHtml(String(raw));
    }
    return `<span class="param-badge">${escapeHtml(label)}</span><span class="param-value">${valueHtml}</span>`;
  });
  return cells.length ? `<div class="params-grid">${cells.join("")}</div>` : '<span class="muted">—</span>';
}

function runRow(r) {
  const when = formatTs(r.ts);
  const statusText = STATUS_LABELS[r.status] || r.status;
  const dl = r.status === "done"
    ? `<a class="btn secondary" href="${api.downloadUrl(reportId, r.file)}">Скачать</a>`
    : "";
  const del = r.status !== "running"
    ? `<button class="btn danger" data-delete="${escapeHtml(r.file)}">Удалить</button>`
    : "";
  const errTitle = r.status === "error" ? ` title="${escapeHtml(r.error || "")}"` : "";
  return `<tr>
    <td>${when}</td>
    <td><span class="status ${r.status}"${errTitle}>${statusText}</span></td>
    <td>${formatSize(r.size_bytes)}</td>
    <td>${formatParamsCell(r.params)}</td>
    <td class="actions">${dl}${del}</td>
  </tr>`;
}

async function onDelete(filename) {
  if (!confirm("Удалить этот файл отчёта?")) return;
  try {
    await api.deleteRun(reportId, filename);
    loadHistory();
  } catch (e) {
    alert(e.message);
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(loadHistory, CLIENT_CONFIG.HISTORY_POLL_INTERVAL_MS);
}
function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

init();
