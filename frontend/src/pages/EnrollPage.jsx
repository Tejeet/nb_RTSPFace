import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";

function formatDate(iso) {
  return new Date(iso).toLocaleDateString();
}

export default function EnrollPage() {
  const inputRef = useRef(null);
  const [name, setName] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [persons, setPersons] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  function load() {
    api.listPersons().then((r) => setPersons(r.items)).catch(() => {});
  }
  useEffect(load, []);

  function pickFile(f) {
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
  }

  async function submit(event) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!file) {
      setError("Please choose a photo.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.enrollPerson(name, employeeId, file);
      setNotice(res.message);
      setName("");
      setEmployeeId("");
      setFile(null);
      setPreview(null);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id, personName) {
    if (!window.confirm(`Remove ${personName} from enrolled persons?`)) return;
    await api.deletePerson(id);
    load();
  }

  return (
    <div>
      <header className="page-header">
        <h1>Enroll Person</h1>
        <span className="muted">{persons.length} enrolled</span>
      </header>

      <div className="enroll-layout">
        <form className="enroll-form" onSubmit={submit}>
          <div
            className="dropzone enroll-drop"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              pickFile(e.dataTransfer.files[0]);
            }}
          >
            {preview ? (
              <img src={preview} alt="Preview" className="enroll-preview" />
            ) : (
              <p>Drop a clear face photo here, or click to choose</p>
            )}
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => pickFile(e.target.files[0])}
            />
          </div>

          <label className="field">
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label className="field">
            <span>Employee ID</span>
            <input
              value={employeeId}
              onChange={(e) => setEmployeeId(e.target.value)}
              required
            />
          </label>

          <button className="button button-primary" disabled={busy}>
            {busy ? "Enrolling…" : "Enroll"}
          </button>
          {notice && <p className="notice">{notice}</p>}
          {error && <p className="error">{error}</p>}
        </form>

        <div className="enroll-list">
          <h2 className="section-title">Enrolled persons</h2>
          {persons.length === 0 && <p className="muted">No one enrolled yet.</p>}
          {persons.map((p) => (
            <div key={p.id} className="person-row">
              <img src={p.photo_url} alt={p.name} />
              <div className="person-info">
                <div className="person-name">{p.name}</div>
                <div className="muted">
                  ID {p.employee_id} · enrolled {formatDate(p.created_at)}
                </div>
              </div>
              <button className="button button-danger" onClick={() => remove(p.id, p.name)}>
                Remove
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
