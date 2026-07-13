import { useRef, useState } from "react";
import { api } from "../lib/api.js";
import FaceCard from "../components/FaceCard.jsx";

export default function SearchPage() {
  const inputRef = useRef(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleFile(file) {
    if (!file) return;
    setPreview(URL.createObjectURL(file));
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.search(file, 10));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <header className="page-header">
        <h1>Face Search</h1>
        <span className="muted">Upload a photo to find similar stored faces</span>
      </header>

      <div
        className="dropzone"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          handleFile(e.dataTransfer.files[0]);
        }}
      >
        {preview ? (
          <img src={preview} alt="Query" className="query-preview" />
        ) : (
          <p>Drop an image here, or click to choose a file</p>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => handleFile(e.target.files[0])}
        />
      </div>

      {busy && <p className="muted">Searching…</p>}
      {error && <p className="error">{error}</p>}

      {result && (
        <>
          <h2 className="section-title">
            {result.query_faces_detected === 0
              ? "No face detected in the uploaded image"
              : `Top ${result.matches.length} matches`}
          </h2>
          <div className="face-grid">
            {result.matches.map((match) => (
              <FaceCard key={match.face.id} face={match.face} similarity={match.similarity} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
