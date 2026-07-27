import { useEffect, useState } from "react";
import { api } from "../lib/api.js";

export default function CamerasPage() {
  const [cameras, setCameras] = useState([]);
  const [name, setName] = useState("");
  const [rtspUrl, setRtspUrl] = useState("");
  const [camId, setCamId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  function load() {
    api.listCameras().then((r) => setCameras(r.items)).catch(() => {});
  }
  useEffect(load, []);

  async function add(event) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await api.addCamera(name, rtspUrl, camId.trim() ? Number(camId) : null);
      setNotice("Camera added — restart the backend to start streaming it.");
      setName("");
      setRtspUrl("");
      setCamId("");
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id, camName) {
    if (!window.confirm(`Remove camera "${camName}"? Captured faces are kept.`)) return;
    try {
      await api.deleteCamera(id);
      setNotice("Camera removed — restart the backend to apply.");
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div>
      <header className="page-header">
        <h1>Cameras</h1>
        <span className="muted">{cameras.length} configured</span>
      </header>

      <div className="enroll-layout">
        <form className="enroll-form" onSubmit={add}>
          <h2 className="section-title" style={{ marginTop: 0 }}>Add camera</h2>
          <label className="field">
            <span>Name (e.g. Entrance, Exit)</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label className="field">
            <span>RTSP URL</span>
            <input
              value={rtspUrl}
              onChange={(e) => setRtspUrl(e.target.value)}
              placeholder="rtsp://user:pass@192.168.1.10:554/Streaming/Channels/101"
              required
            />
          </label>
          <label className="field">
            <span>Camera ID (optional — leave blank to auto-assign)</span>
            <input
              value={camId}
              onChange={(e) => setCamId(e.target.value)}
              inputMode="numeric"
              placeholder="e.g. 601"
            />
          </label>
          <button className="button button-primary" disabled={busy}>
            {busy ? "Adding…" : "Add camera"}
          </button>
          {notice && <p className="notice">{notice}</p>}
          {error && <p className="error">{error}</p>}
          <p className="muted settings-note">
            New cameras and removals take effect when the backend restarts
            (<code>docker compose restart backend</code>). Passwords with special
            characters must be URL-encoded (<code>@</code> → <code>%40</code>).
          </p>
        </form>

        <div className="enroll-list">
          <h2 className="section-title">Configured cameras</h2>
          {cameras.map((c) => (
            <div key={c.id} className="person-row">
              <div className={`dot ${c.connected ? "dot-ok" : "dot-bad"}`} />
              <div className="person-info">
                <div className="person-name">
                  {c.name} <span className="muted">· id {c.id}</span>
                </div>
                <div className="muted camera-url">{c.rtsp_url}</div>
                <div className="muted">
                  {c.running
                    ? c.connected
                      ? "running · connected"
                      : "running · connecting…"
                    : "not started (restart backend)"}
                </div>
              </div>
              <button className="button button-danger" onClick={() => remove(c.id, c.name)}>
                Remove
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
