import { useEffect, useState } from "react";
import { api } from "../lib/api.js";

export default function SettingsPage() {
  const [info, setInfo] = useState(null);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getInferenceSettings()
      .then((data) => {
        setInfo(data);
        setSelected(data.inference_backend);
      })
      .catch((e) => setError(e.message));
  }, []);

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await api.setInferenceSettings(selected);
      setInfo(updated);
      setSaved(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !info) return <p className="error">{error}</p>;
  if (!info) return <p className="muted">Loading settings…</p>;

  return (
    <div>
      <header className="page-header">
        <h1>Settings</h1>
      </header>

      <section className="settings-card">
        <h2 className="section-title">Processing hardware</h2>
        <p className="muted settings-note">
          Choose how the RTSP feed is processed. NPU mode uses the board&apos;s neural
          accelerator (e.g. Radxa Cubie A7Z — 3 TOPS) through an ONNX Runtime NPU
          execution provider, and falls back to CPU automatically if no NPU runtime
          is installed.
        </p>

        <label className={`radio-row${selected === "cpu" ? " selected" : ""}`}>
          <input
            type="radio"
            name="backend"
            checked={selected === "cpu"}
            onChange={() => setSelected("cpu")}
          />
          <div>
            <div className="radio-title">CPU</div>
            <div className="muted">ONNX Runtime on CPU cores — works everywhere</div>
          </div>
        </label>

        <label className={`radio-row${selected === "npu" ? " selected" : ""}`}>
          <input
            type="radio"
            name="backend"
            checked={selected === "npu"}
            onChange={() => setSelected("npu")}
          />
          <div>
            <div className="radio-title">
              NPU (on-SoC){" "}
              {info.npu_runtime_available ? (
                <span className="badge badge-quality">runtime detected</span>
              ) : (
                <span className="badge badge-dup">runtime not installed</span>
              )}
            </div>
            <div className="muted">
              Built-in accelerator via ONNX Runtime — Radxa Cubie A7Z (VSINPU),
              Rockchip (RKNPU)
            </div>
          </div>
        </label>

        <label className={`radio-row${selected === "hailo" ? " selected" : ""}`}>
          <input
            type="radio"
            name="backend"
            checked={selected === "hailo"}
            onChange={() => setSelected("hailo")}
          />
          <div>
            <div className="radio-title">
              Hailo-8 (PCIe){" "}
              {info.hailo_runtime_available ? (
                <span className="badge badge-quality">HailoRT installed</span>
              ) : (
                <span className="badge badge-dup">HailoRT missing</span>
              )}{" "}
              {info.hailo_device_present ? (
                <span className="badge badge-quality">/dev/hailo0 present</span>
              ) : (
                <span className="badge badge-dup">no device node</span>
              )}
            </div>
            <div className="muted">
              SCRFD detection on the Hailo-8 accelerator (compiled .hef models);
              embeddings stay on CPU unless a recognition HEF is configured
            </div>
          </div>
        </label>

        <div className="settings-actions">
          <button
            className="button"
            disabled={busy || selected === info.inference_backend}
            onClick={save}
          >
            Save
          </button>
          {saved && info.requires_restart && (
            <span className="badge badge-dup">
              Saved — restart the backend to apply: docker compose restart backend
            </span>
          )}
          {saved && !info.requires_restart && (
            <span className="badge badge-quality">Saved</span>
          )}
          {error && <span className="error">{error}</span>}
        </div>
      </section>

      <section className="settings-card">
        <h2 className="section-title">Current inference state</h2>
        <table className="meta-table">
          <tbody>
            <tr>
              <td>Running backend</td>
              <td>{info.running_backend.toUpperCase()}</td>
            </tr>
            <tr>
              <td>NPU in use</td>
              <td>{info.npu_active ? "Yes" : "No"}</td>
            </tr>
            <tr>
              <td>Hailo-8 in use</td>
              <td>{info.hailo_active ? "Yes" : "No"}</td>
            </tr>
            <tr>
              <td>Active ONNX providers</td>
              <td>{info.active_providers.join(", ") || "—"}</td>
            </tr>
            <tr>
              <td>Model pack</td>
              <td>{info.model_pack}</td>
            </tr>
            <tr>
              <td>Detector input size</td>
              <td>{info.detection_size}×{info.detection_size}</td>
            </tr>
          </tbody>
        </table>
        {info.backend_error && (
          <p className="settings-note backend-error">
            <strong>Fell back to CPU:</strong> {info.backend_error}
          </p>
        )}
        {!info.npu_runtime_available && !info.hailo_runtime_available && (
          <p className="muted settings-note">
            No accelerator runtime is installed in this container. NPU mode needs an
            ONNX Runtime build with the board&apos;s execution provider; Hailo mode needs
            HailoRT plus compiled <code>.hef</code> models (see docs/DEPLOYMENT.md).
            Either option safely runs on CPU until then.
          </p>
        )}
      </section>
    </div>
  );
}
