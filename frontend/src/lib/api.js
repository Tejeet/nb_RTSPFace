// Thin REST client. All endpoints are same-origin (nginx / vite proxy).

async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export const api = {
  recentFaces: (limit = 24) => request(`/api/recent?limit=${limit}`),
  listFaces: (limit = 50, offset = 0) =>
    request(`/api/faces?limit=${limit}&offset=${offset}`),
  getFace: (id) => request(`/api/faces/${id}`),
  deleteFace: (id) => request(`/api/faces/${id}`, { method: "DELETE" }),
  statistics: () => request("/api/statistics"),
  health: () => request("/api/health"),
  liveStatus: () => request("/api/live-status"),
  search: (file, topK = 10) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/search?top_k=${topK}`, { method: "POST", body: form });
  },
  getInferenceSettings: () => request("/api/settings/inference"),
  setInferenceSettings: (backend) =>
    request("/api/settings/inference", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inference_backend: backend }),
    }),
  getZone: () => request("/api/zone"),
  setZone: (points) =>
    request("/api/zone", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ points }),
    }),
  clearZone: () => request("/api/zone", { method: "DELETE" }),
};
