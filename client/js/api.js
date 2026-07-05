// Тонкая обёртка над fetch. Чистый JS, без зависимостей.
const api = (() => {
  async function request(method, url, body) {
    const res = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Ошибка запроса (${res.status})`);
    }
    return res.json();
  }

  return {
    listReports: () => request("GET", "/api/reports"),
    getReport: (id) => request("GET", `/api/reports/${encodeURIComponent(id)}`),
    createReport: (data) => request("POST", "/api/reports", data),
    updateReport: (id, data) => request("PUT", `/api/reports/${encodeURIComponent(id)}`, data),
    previewColumns: (connector, query) => request("POST", "/api/preview-columns", { connector, query }),
    paramOptions: (reportId, paramName) =>
      request("GET", `/api/reports/${encodeURIComponent(reportId)}/params/${encodeURIComponent(paramName)}/options`),
    runReport: (id, params) => request("POST", `/api/reports/${encodeURIComponent(id)}/run`, { params }),
    listRuns: (id) => request("GET", `/api/reports/${encodeURIComponent(id)}/runs`),
    deleteRun: (id, file) =>
      request("DELETE", `/api/reports/${encodeURIComponent(id)}/runs/${encodeURIComponent(file)}`),
    downloadUrl: (id, file) =>
      `/api/reports/${encodeURIComponent(id)}/runs/${encodeURIComponent(file)}/download`,
  };
})();
