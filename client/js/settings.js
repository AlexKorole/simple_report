const urlParams = new URLSearchParams(window.location.search);
const editId = urlParams.get("id"); // null = создание нового отчёта
let loadedColumns = [];
let existingMapping = {};

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

async function init() {
  document.getElementById("loadColumnsBtn").addEventListener("click", loadColumns);
  document.getElementById("addParamBtn").addEventListener("click", () => addParamRow());
  document.getElementById("saveBtn").addEventListener("click", save);
  document.getElementById("closeBtn").addEventListener("click", () => {
    window.location.href = editId ? `/report.html?id=${encodeURIComponent(editId)}` : "/index.html";
  });
  document.getElementById("f_id").addEventListener("input", (e) => {
    e.target.value = e.target.value.replace(/[^A-Za-z0-9_-]/g, "");
  });

  await loadConnectorOptions();

  if (editId) {
    document.getElementById("pageTitle").textContent = "Настройки отчёта";
    document.getElementById("f_id").disabled = true;
    try {
      const cfg = await api.getReport(editId);
      fillForm(cfg);
    } catch (e) {
      document.getElementById("saveMsg").textContent = e.message;
    }
  }
}

async function loadConnectorOptions() {
  const select = document.getElementById("f_connector");
  try {
    const connectors = await api.listConnectors();
    select.innerHTML = connectors.map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join("");
  } catch (e) {
    select.innerHTML = '<option value="postgresql">PostgreSQL</option>';
  }
}

function fillForm(cfg) {
  document.getElementById("f_id").value = cfg.id || "";
  document.getElementById("f_name").value = cfg.name || "";
  document.getElementById("f_description").value = cfg.description || "";
  document.getElementById("f_connector").value = cfg.connector || "postgresql";
  document.getElementById("f_sql").value = cfg.sql || "";
  document.getElementById("f_columns_query").value = cfg.columns_query || "";
  existingMapping = cfg.column_mapping || {};
  loadedColumns = Object.keys(existingMapping);
  renderColumnsList();
  for (const p of cfg.params || []) addParamRow(p);
}

async function loadColumns() {
  const msg = document.getElementById("columnsMsg");
  msg.textContent = "Загружаю…";
  // сохраняем то, что уже введено в текущих полях, прежде чем перерисовать список
  existingMapping = { ...existingMapping, ...collectColumnMapping() };
  try {
    const connector = document.getElementById("f_connector").value.trim();
    const query = document.getElementById("f_columns_query").value;
    const columns = await api.previewColumns(connector, query);
    loadedColumns = columns;
    msg.textContent = `Найдено колонок: ${columns.length}`;
    renderColumnsList();
  } catch (e) {
    msg.textContent = e.message;
  }
}

function renderColumnsList() {
  const el = document.getElementById("columnsList");
  if (loadedColumns.length === 0) {
    el.innerHTML = '<p class="muted">Колонки ещё не загружены.</p>';
    return;
  }
  el.innerHTML = loadedColumns.map((col) => `
    <label>${escapeHtml(col)} → название в CSV
      <input class="col-mapping" data-col="${escapeHtml(col)}" value="${escapeHtml(existingMapping[col] || col)}" />
    </label>
  `).join("");
}

function collectColumnMapping() {
  const mapping = {};
  document.querySelectorAll(".col-mapping").forEach((input) => {
    mapping[input.dataset.col] = input.value;
  });
  return mapping;
}

function addParamRow(p) {
  const wrap = document.createElement("div");
  wrap.className = "card";
  wrap.innerHTML = `
    <label>Имя переменной (как в SQL)
      <input class="p_name" value="${escapeHtml(p?.name || "")}" />
    </label>
    <label>Подпись для пользователя
      <input class="p_view_name" value="${escapeHtml(p?.view_name || "")}" />
    </label>
    <label>Тип
      <select class="p_type">
        <option value="string">Текст</option>
        <option value="number">Число</option>
        <option value="date">Дата</option>
        <option value="multilist">Список (мультивыбор)</option>
      </select>
    </label>
    <label class="p_list_query_wrap" style="display:none">SQL для списка значений (1-я колонка — значение, 2-я опционально — подпись)
      <textarea class="p_list_query code-input" rows="2"></textarea>
    </label>
    <label class="p_min_wrap" style="display:none">SQL для подсказки "мин." (необязательно, одна колонка)
      <input class="p_min_query" />
    </label>
    <label class="p_max_wrap" style="display:none">SQL для подсказки "макс." (необязательно, одна колонка)
      <input class="p_max_query" />
    </label>
    <button class="btn secondary p_remove" type="button">Удалить параметр</button>
  `;
  wrap.querySelector(".p_type").value = p?.type || "string";
  wrap.querySelector(".p_list_query").value = p?.list_query || "";
  wrap.querySelector(".p_min_query").value = p?.min_query || "";
  wrap.querySelector(".p_max_query").value = p?.max_query || "";

  const typeSelect = wrap.querySelector(".p_type");
  const listWrap = wrap.querySelector(".p_list_query_wrap");
  const minWrap = wrap.querySelector(".p_min_wrap");
  const maxWrap = wrap.querySelector(".p_max_wrap");
  const sync = () => {
    listWrap.style.display = typeSelect.value === "multilist" ? "" : "none";
    const showDateHints = typeSelect.value === "date";
    minWrap.style.display = showDateHints ? "" : "none";
    maxWrap.style.display = showDateHints ? "" : "none";
  };
  typeSelect.addEventListener("change", sync);
  sync();

  wrap.querySelector(".p_remove").addEventListener("click", () => wrap.remove());
  document.getElementById("paramsList").appendChild(wrap);
}

function collectParams() {
  return Array.from(document.querySelectorAll("#paramsList > div")).map((wrap) => {
    const param = {
      name: wrap.querySelector(".p_name").value.trim(),
      view_name: wrap.querySelector(".p_view_name").value.trim(),
      type: wrap.querySelector(".p_type").value,
    };
    if (param.type === "multilist") {
      const lq = wrap.querySelector(".p_list_query").value.trim();
      if (lq) param.list_query = lq;
    }
    if (param.type === "date") {
      const minQ = wrap.querySelector(".p_min_query").value.trim();
      const maxQ = wrap.querySelector(".p_max_query").value.trim();
      if (minQ) param.min_query = minQ;
      if (maxQ) param.max_query = maxQ;
    }
    return param;
  });
}

const ID_RE = /^[A-Za-z0-9_-]+$/;

async function save() {
  const msg = document.getElementById("saveMsg");
  const id = document.getElementById("f_id").value.trim();
  if (!id) {
    msg.textContent = "Укажите идентификатор";
    return;
  }
  if (!ID_RE.test(id)) {
    msg.textContent = "Идентификатор может содержать только латинские буквы, цифры, _ и -";
    return;
  }
  msg.textContent = "Сохраняю…";
  const payload = {
    id,
    name: document.getElementById("f_name").value.trim(),
    description: document.getElementById("f_description").value.trim(),
    connector: document.getElementById("f_connector").value.trim(),
    sql: document.getElementById("f_sql").value,
    columns_query: document.getElementById("f_columns_query").value.trim() || null,
    column_mapping: collectColumnMapping(),
    params: collectParams(),
  };
  try {
    if (editId) {
      await api.updateReport(editId, payload);
      msg.textContent = "Сохранено.";
    } else {
      await api.createReport(payload);
      msg.textContent = "Сохранено, переходим к отчёту…";
      window.location.href = `/settings.html?id=${encodeURIComponent(id)}`;
    }
  } catch (e) {
    msg.textContent = e.message;
  }
}

init();
