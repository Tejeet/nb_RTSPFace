import { Link } from "react-router-dom";

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function FaceCard({ face, similarity }) {
  return (
    <Link to={`/faces/${face.id}`} className="face-card">
      <img src={face.thumbnail_url} alt={`Face ${face.id}`} loading="lazy" />
      <div className="face-card-body">
        <div className="face-card-row">
          <span className="face-time">{formatTime(face.captured_at)}</span>
          <span className="badge badge-track">ID {face.track_id}</span>
        </div>
        <div className="face-card-row">
          <span className="badge badge-quality">
            Q {(face.quality_score * 100).toFixed(0)}%
          </span>
          {similarity != null && (
            <span className="badge badge-sim">{(similarity * 100).toFixed(1)}%</span>
          )}
          {similarity == null && face.is_possible_duplicate === 1 && (
            <span className="badge badge-dup">dup?</span>
          )}
        </div>
      </div>
    </Link>
  );
}
