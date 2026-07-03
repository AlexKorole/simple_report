function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

async function init() {
  const listEl = document.getElementById("list");
  try {
    const reports = await api.listReports();
    if (reports.length === 0) {
      listEl.innerHTML = '<p class="muted">Пока нет отчётов. Добавьте .json в server/configs/.</p>';
      return;
    }
    listEl.innerHTML = "";
    for (const r of reports) {
      const a = document.createElement("a");
      a.className = "report-item";
      a.href = `/report.html?id=${encodeURIComponent(r.id)}`;
      a.innerHTML = `<div>${escapeHtml(r.name)}</div>` +
        (r.description ? `<div class="desc">${escapeHtml(r.description)}</div>` : "");
      listEl.appendChild(a);
    }
  } catch (e) {
    listEl.innerHTML = `<p class="error-box">${escapeHtml(e.message)}</p>`;
  }
}

init();
