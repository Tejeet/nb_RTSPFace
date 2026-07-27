import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { useEvent } from "../lib/useEvents.js";
import FaceCard from "../components/FaceCard.jsx";
import ZoneEditor from "../components/ZoneEditor.jsx";

export default function LivePage() {
  const [cameras, setCameras] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [status, setStatus] = useState(null);
  const [recent, setRecent] = useState([]);
  const imgRef = useRef(null);
  const containerRef = useRef(null);

  // Load cameras once; default to the first.
  useEffect(() => {
    api.listCameras().then((r) => {
      setCameras(r.items);
      if (r.items.length) setActiveId((cur) => cur ?? r.items[0].id);
    });
    api.recentFaces(8).then(setRecent).catch(() => {});
  }, []);

  // Poll live status for the selected camera (the WS event only covers one).
  useEffect(() => {
    if (activeId == null) return;
    let alive = true;
    const tick = () =>
      api
        .liveStatus(activeId)
        .then((s) => alive && setStatus(s))
        .catch(() => {});
    tick();
    const t = setInterval(tick, 1500);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [activeId]);

  useEvent("face_captured", (face) => {
    if (activeId == null || face.camera_id === activeId) {
      setRecent((current) => [face, ...current].slice(0, 8));
    }
  });

  const multi = cameras.length > 1;

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
              <span className="people-count">{status.faces_in_frame ?? 0} people in frame</span>
              <span className="meta-sep">·</span>
              <span>{status.tracked_faces} tracked</span>
            </>
          )}
        </div>
      </header>

      {multi && (
        <div className="camera-tabs">
          {cameras.map((c) => (
            <button
              key={c.id}
              className={`camera-tab${c.id === activeId ? " active" : ""}`}
              onClick={() => setActiveId(c.id)}
            >
              <span className={`dot ${c.connected ? "dot-ok" : "dot-bad"}`} />
              {c.name}
            </button>
          ))}
        </div>
      )}

      <div className="live-frame" ref={containerRef}>
        {status?.camera_connected === false ? (
          <div className="live-offline">Camera offline — reconnecting automatically…</div>
        ) : (
          activeId != null && (
            <img
              key={activeId}
              ref={imgRef}
              src={`/api/stream/live?camera_id=${activeId}`}
              alt="Live camera stream"
            />
          )
        )}
        <ZoneEditor imgRef={imgRef} containerRef={containerRef} cameraId={activeId} />
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
