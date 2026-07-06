function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

async function init() {
  applyStaticTranslations();
  const listEl = document.getElementById("list");
  try {
    const reports = await api.listReports();
    if (reports.length === 0) {
      listEl.innerHTML = `<p class="muted">${escapeHtml(t("reports.empty"))}</p>`;
      return;
    }
    listEl.innerHTML = "";
    for (const r of reports) {
      const a = document.createElement("a");
      a.className = "report-item";
      a.href = `/report.html?id=${encodeURIComponent(r.id)}`;
      a.innerHTML = `
        <div class="report-item-row">
          <div>
            <div>${escapeHtml(r.name)}</div>
            ${r.description ? `<div class="desc">${escapeHtml(r.description)}</div>` : ""}
          </div>
          <button type="button" class="btn danger report-delete-btn" data-id="${escapeHtml(r.id)}">${escapeHtml(t("reports.delete"))}</button>
        </div>`;
      listEl.appendChild(a);
    }
    listEl.querySelectorAll(".report-delete-btn").forEach((btn) => {
      btn.addEventListener("click", onDeleteReport);
    });
  } catch (e) {
    listEl.innerHTML = `<p class="error-box">${escapeHtml(e.message)}</p>`;
  }
}

async function onDeleteReport(event) {
  event.preventDefault();
  event.stopPropagation();
  const id = event.currentTarget.dataset.id;
  if (!confirm(t("reports.deleteConfirm"))) return;
  try {
    await api.deleteReport(id);
    init();
  } catch (e) {
    alert(e.message);
  }
}

init();
