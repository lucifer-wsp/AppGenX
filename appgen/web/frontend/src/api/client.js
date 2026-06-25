const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function request(url, options = {}) {
  const res = await fetch(url, options)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || res.statusText || '请求失败')
  return data
}

export const api = {
  listRuns: () => request('/api/runs'),
  getRun: (id) => request(`/api/runs/${id}`),
  getProgress: (id) => request(`/api/runs/${id}/progress`),
  getStageDocuments: (runId, stage) => request(`/api/runs/${runId}/stages/${stage}/documents`),
  getDocument: (runId, name) => request(`/api/runs/${runId}/documents/${encodeURIComponent(name)}`),
  resumeRun: (id) => request(`/api/runs/${id}/resume`, { method: 'POST' }),
  setAutoReview: (id, enabled) =>
    request(`/api/runs/${id}/auto-review`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify({ enabled }),
    }),
  submitReview: (runId, stage, action, notes) =>
    request(`/api/runs/${runId}/review/${stage}/${action}`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ notes }),
    }),

  listGenres: () => request('/api/genres'),
  listScans: () => request('/api/scans'),
  estimateScan: (body) =>
    request('/api/scans/estimate', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body) }),
  createScan: (body) =>
    request('/api/scans', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body) }),
  getScan: (id) => request(`/api/scans/${id}`),
  reanalyzeScan: (id) => request(`/api/scans/${id}/reanalyze`, { method: 'POST' }),
  cancelScan: (id) => request(`/api/scans/${id}/cancel`, { method: 'POST' }),
  getScanPreferences: () => request('/api/scan-preferences'),
  submitOpportunityFeedback: (scanId, body) =>
    request(`/api/scans/${scanId}/opportunities/feedback`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    }),
  deleteScanPreference: (id) =>
    request(`/api/scan-preferences/${id}`, { method: 'DELETE' }),
  pickOpportunity: (scanId, rank, options = {}) =>
    request(`/api/scans/${scanId}/pick`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ rank, auto_review: !!options.autoReview }),
    }),

  getSettings: () => request('/api/settings'),
  updateSettings: (body) =>
    request('/api/settings', {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    }),
  reloadSettings: () => request('/api/settings/reload', { method: 'POST' }),
}
