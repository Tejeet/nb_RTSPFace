import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api.js";

function formatDateTime(iso) {
  return new Date(iso).toLocaleString();
}

export default function FaceDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [face, setFace] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getFace(id).then(setFace).catch((e) => setError(e.message));
  }, [id]);

  async function handleDelete() {
    if (!window.confirm(`Delete face #${id}? This removes the image, embedding and index entry.`))
      return;
    await api.deleteFace(id);
    navigate("/recent");
  }

  if (error) return <p className="error">{error}</p>;
  if (!face) return <p className="muted">Loading…</p>;

  const rows = [
    ["Captured", formatDateTime(face.captured_at)],
    ["Camera", face.camera_name],
    ["Track ID", face.track_id],
    ["UUID", face.uuid],
    ["Quality score", `${(face.quality_score * 100).toFixed(1)}%`],
    ["Detection confidence", `${(face.detection_confidence * 100).toFixed(1)}%`],
    ["Bounding box", `x=${face.bbox.x} y=${face.bbox.y} ${face.bbox.w}×${face.bbox.h}`],
    ["Image size", `${face.image_width}×${face.image_height} (${(face.file_size_bytes / 1024).toFixed(1)} KB)`],
    ["Embedding model", face.embedding_model ?? "—"],
    ["Embedding file", face.embedding_path ?? "—"],
  ];

  return (
    <div>
      <header className="page-header">
        <h1>Face #{face.id}</h1>
        <div className="header-actions">
          <a className="button" href={face.image_url} download={`face_${face.uuid}.jpg`}>
            ⬇ Download image
          </a>
          <button className="button button-danger" onClick={handleDelete}>
            Delete
          </button>
        </div>
      </header>

      <div className="detail-layout">
        <div className="detail-image">
          <img src={face.image_url} alt={`Face ${face.id}`} />
          {face.is_possible_duplicate === 1 && (
            <div className="badge badge-dup detail-dup">Possible duplicate</div>
          )}
        </div>

        <div className="detail-meta">
          <table className="meta-table">
            <tbody>
              {rows.map(([label, value]) => (
                <tr key={label}>
                  <td>{label}</td>
                  <td>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2 className="section-title">Similarity matches</h2>
          {face.duplicates.length === 0 && (
            <p className="muted">No near-duplicates recorded.</p>
          )}
          <div className="dup-list">
            {face.duplicates.map((dup) => (
              <Link key={dup.face_id} to={`/faces/${dup.face_id}`} className="dup-item">
                <img src={dup.thumbnail_url} alt={`Face ${dup.face_id}`} />
                <div>
                  <div>Face #{dup.face_id}</div>
                  <div className="badge badge-sim">{(dup.similarity * 100).toFixed(1)}%</div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
