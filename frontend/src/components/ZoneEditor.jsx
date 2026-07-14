import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";

/**
 * Draws the capture zone (region of interest) over the live stream.
 *
 * Click points on the video to trace a polygon; Save pushes it to the
 * backend where it takes effect immediately. The saved zone is burned
 * into the stream itself (orange), so this overlay only renders the
 * in-progress polygon while editing.
 */
export default function ZoneEditor({ imgRef, containerRef }) {
  const [editing, setEditing] = useState(false);
  const [points, setPoints] = useState([]);
  const [zoneActive, setZoneActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [rect, setRect] = useState(null);
  const svgRef = useRef(null);

  useEffect(() => {
    api.getZone().then((zone) => setZoneActive(zone.enabled)).catch(() => {});
  }, []);

  // Compute where the (object-fit: contain) video actually renders inside
  // its container, so clicks map to true image coordinates.
  const computeRect = useCallback(() => {
    const img = imgRef.current;
    const box = containerRef.current;
    if (!img || !box || !img.naturalWidth) return;
    const cw = box.clientWidth;
    const ch = box.clientHeight;
    const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
    const width = img.naturalWidth * scale;
    const height = img.naturalHeight * scale;
    setRect({ left: (cw - width) / 2, top: (ch - height) / 2, width, height });
  }, [imgRef, containerRef]);

  useEffect(() => {
    if (!editing) return;
    computeRect();
    const interval = setInterval(computeRect, 500); // track stream/layout changes
    window.addEventListener("resize", computeRect);
    return () => {
      clearInterval(interval);
      window.removeEventListener("resize", computeRect);
    };
  }, [editing, computeRect]);

  function handleClick(event) {
    const bounds = svgRef.current.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / bounds.width;
    const y = (event.clientY - bounds.top) / bounds.height;
    setPoints((current) => [
      ...current,
      [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))],
    ]);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.setZone(points);
      setZoneActive(true);
      setEditing(false);
      setPoints([]);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function clearZone() {
    setBusy(true);
    setError(null);
    try {
      await api.clearZone();
      setZoneActive(false);
      setEditing(false);
      setPoints([]);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {editing && rect && (
        <svg
          ref={svgRef}
          className="zone-overlay"
          style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          onClick={handleClick}
        >
          {points.length >= 2 && (
            <polygon
              points={points.map(([x, y]) => `${x * 100},${y * 100}`).join(" ")}
              className="zone-polygon"
            />
          )}
          {points.map(([x, y], index) => (
            <circle key={index} cx={x * 100} cy={y * 100} r="1.2" className="zone-point" />
          ))}
        </svg>
      )}

      <div className="zone-toolbar">
        {!editing ? (
          <>
            <button className="button" onClick={() => setEditing(true)}>
              ✏️ {zoneActive ? "Edit zone" : "Draw capture zone"}
            </button>
            {zoneActive && (
              <button className="button" disabled={busy} onClick={clearZone}>
                Clear zone
              </button>
            )}
          </>
        ) : (
          <>
            <span className="muted">
              Click on the video to add points ({points.length} placed, need ≥ 3)
            </span>
            <button
              className="button"
              disabled={points.length === 0}
              onClick={() => setPoints(points.slice(0, -1))}
            >
              Undo
            </button>
            <button className="button" disabled={points.length < 3 || busy} onClick={save}>
              ✔ Save zone
            </button>
            <button
              className="button"
              onClick={() => {
                setEditing(false);
                setPoints([]);
                setError(null);
              }}
            >
              Cancel
            </button>
          </>
        )}
        {error && <span className="error">{error}</span>}
      </div>
    </>
  );
}
