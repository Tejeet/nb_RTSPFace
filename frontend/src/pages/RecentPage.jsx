import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { useEvent } from "../lib/useEvents.js";
import FaceCard from "../components/FaceCard.jsx";

const PAGE_SIZE = 48;

export default function RecentPage() {
  const [faces, setFaces] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .listFaces(PAGE_SIZE, offset)
      .then((response) => {
        setFaces(response.items);
        setTotal(response.total);
      })
      .catch((e) => setError(e.message));
  }, [offset]);

  // Live-prepend new captures while viewing the first page.
  useEvent("face_captured", (face) => {
    if (offset === 0) {
      setFaces((current) => [face, ...current].slice(0, PAGE_SIZE));
      setTotal((t) => t + 1);
    }
  });

  return (
    <div>
      <header className="page-header">
        <h1>Recent Captures</h1>
        <span className="muted">{total} faces stored</span>
      </header>

      {error && <p className="error">{error}</p>}

      <div className="face-grid">
        {faces.map((face) => (
          <FaceCard key={face.id} face={face} />
        ))}
        {faces.length === 0 && !error && <p className="muted">No faces captured yet.</p>}
      </div>

      <div className="pager">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        >
          ← Newer
        </button>
        <span className="muted">
          {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
        </span>
        <button
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Older →
        </button>
      </div>
    </div>
  );
}
