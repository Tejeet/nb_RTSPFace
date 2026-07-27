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
  listCameras: () => request("/api/cameras"),
  addCamera: (name, rtspUrl) =>
    request("/api/cameras", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, rtsp_url: rtspUrl }),
    }),
  deleteCamera: (id) => request(`/api/cameras/${id}`, { method: "DELETE" }),
  liveStatus: (cameraId) =>
    request(`/api/live-status${cameraId != null ? `?camera_id=${cameraId}` : ""}`),
  recentFaces: (limit = 24) => request(`/api/recent?limit=${limit}`),
  listFaces: (limit = 50, offset = 0) =>
    request(`/api/faces?limit=${limit}&offset=${offset}`),
  getFace: (id) => request(`/api/faces/${id}`),
  deleteFace: (id) => request(`/api/faces/${id}`, { method: "DELETE" }),
  statistics: () => request("/api/statistics"),
  health: () => request("/api/health"),
  search: (file, topK = 10) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/search?top_k=${topK}`, { method: "POST", body: form });
  },
  listPersons: () => request("/api/persons"),
  enrollPerson: (name, employeeId, file) => {
    const form = new FormData();
    form.append("name", name);
    form.append("employee_id", employeeId);
    form.append("file", file);
    return request("/api/persons", { method: "POST", body: form });
  },
  deletePerson: (id) => request(`/api/persons/${id}`, { method: "DELETE" }),
  purgeFaces: (scope) =>
    request("/api/faces/purge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope }),
    }),
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
