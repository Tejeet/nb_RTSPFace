import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { useEvent, useEventState } from "../lib/useEvents.js";
import FaceCard from "../components/FaceCard.jsx";

export default function LivePage() {
  const status = useEventState("live_status");
  const [recent, setRecent] = useState([]);

  useEffect(() => {
    api.recentFaces(8).then(setRecent).catch(() => {});
  }, []);

  useEvent("face_captured", (face) => {
    setRecent((current) => [face, ...current].slice(0, 8));
  });

  return (
    <div>
      <header className="page-header">
        <h1>Live View</h1>
        <div className="live-meta">
          {status && (
            <>
              <span className={`dot ${status.camera_connected ? "dot-ok" : "dot-bad"}`} />
              <span>{status.camera_name}</span>
              <span className="meta-sep">·</span>
              <span>{status.fps?.toFixed(1)} FPS</span>
              <span className="meta-sep">·</span>
              <span>{status.visible_faces} visible</span>
              <span className="meta-sep">·</span>
              <span>{status.tracked_faces} tracked</span>
            </>
          )}
        </div>
      </header>

      <div className="live-frame">
        {status?.camera_connected === false ? (
          <div className="live-offline">
            Camera offline — reconnecting automatically…
          </div>
        ) : (
          <img src="/api/stream/live" alt="Live camera stream" />
        )}
      </div>

      <h2 className="section-title">Latest captures</h2>
      <div className="face-grid face-grid-compact">
        {recent.map((face) => (
          <FaceCard key={face.id} face={face} />
        ))}
        {recent.length === 0 && <p className="muted">No faces captured yet.</p>}
      </div>
    </div>
  );
}
