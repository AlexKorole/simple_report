const urlParams = new URLSearchParams(window.location.search);
const reportId = urlParams.get("id");
let report = null;
let pollTimer = null;

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
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

function showTab(which) {
  document.getElementById("panelRun").style.display = which === "run" ? "" : "none";
  document.getElementById("panelHistory").style.display = which === "history" ? "" : "none";
  document.getElementById("tabRunBtn").className = which === "run" ? "btn" : "btn secondary";
  document.getElementById("tabHistoryBtn").className = which === "history" ? "btn" : "btn secondary";
  if (which === "history") loadHistory();
  else stopPolling();
}

function renderParamsForm() {
  const form = document.getElementById("paramsForm");
  form.innerHTML = "";
  for (const p of report.params || []) {
    const label = document.createElement("label");
    label.textContent = p.view_name || p.name;

    const row = document.createElement("div");
    row.style.cssText = "display:flex; gap:8px; align-items:center;";

    const input = document.createElement("input");
    input.type = p.type === "date" ? "date" : p.type === "number" ? "number" : "text";
    input.id = `param_${p.name}`;
    input.style.flex = "1";

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

function collectParams() {
  const values = {};
  for (const p of report.params || []) {
    const allChecked = document.getElementById(`param_${p.name}_all`).checked;
    const el = document.getElementById(`param_${p.name}`);
    values[p.name] = allChecked ? "" : el.value;
  }
  return values;
}

async function startRun() {
  const runMsg = document.getElementById("runMsg");
  runMsg.textContent = "Запускаю…";
  try {
    await api.runReport(reportId, collectParams());
    runMsg.textContent = "Готово — выгрузка запущена.";
    showTab("history");
  } catch (e) {
    runMsg.textContent = e.message;
  }
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
    if (runs.length === 0) {
      el.innerHTML = '<p class="muted">Пока нет запусков.</p>';
    } else {
      el.innerHTML = `
        <table>
          <thead><tr><th>Когда</th><th>Статус</th><th>Размер</th><th></th></tr></thead>
          <tbody>${runs.map(runRow).join("")}</tbody>
        </table>`;
      el.querySelectorAll("[data-delete]").forEach((btn) => {
        btn.addEventListener("click", () => onDelete(btn.dataset.delete));
      });
    }
    const active = runs.some((r) => r.status === "running");
    if (active) startPolling();
    else stopPolling();
  } catch (e) {
    el.innerHTML = `<p class="error-box">${escapeHtml(e.message)}</p>`;
  }
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
  pollTimer = setInterval(loadHistory, 3000);
}
function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

init();
