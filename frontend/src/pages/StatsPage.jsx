import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { useEventState } from "../lib/useEvents.js";
import StatCard from "../components/StatCard.jsx";

function formatUptime(seconds) {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function StatsPage() {
  const [initial, setInitial] = useState(null);
  const live = useEventState("stats");
  const stats = live ?? initial;

  useEffect(() => {
    api.statistics().then(setInitial).catch(() => {});
  }, []);

  if (!stats) return <p className="muted">Loading statistics…</p>;

  const tone = (value, warn, bad) =>
    value >= bad ? "bad" : value >= warn ? "warn" : "default";

  return (
    <div>
      <header className="page-header">
        <h1>Statistics</h1>
        <span className="muted">Updates in real time</span>
      </header>

      {stats.inference_label && (
        <div className={`backend-banner backend-${stats.inference_backend}`}>
          <span className="backend-dot" />
          <span>
            Processing on <strong>{stats.inference_label}</strong>
            {stats.inference_backend === "cpu" && " (no accelerator active)"}
          </span>
          {stats.accelerator_temperature_c != null && (
            <span className="backend-temp">
              {stats.accelerator_temperature_c.toFixed(1)} °C
            </span>
          )}
        </div>
      )}

      <h2 className="section-title">Captures</h2>
      <div className="stat-grid">
        <StatCard label="Faces today" value={stats.faces_today} tone="accent" />
        <StatCard label="Faces this hour" value={stats.faces_last_hour} />
        <StatCard label="Total stored" value={stats.faces_total} />
        <StatCard label="Currently tracked" value={stats.current_tracks} />
        <StatCard label="Saved this session" value={stats.faces_saved_session} />
        <StatCard label="Rejected (quality)" value={stats.faces_rejected_session} />
      </div>

      <h2 className="section-title">Pipeline</h2>
      <div className="stat-grid">
        <StatCard label="Camera FPS" value={stats.fps?.toFixed(1)} />
        <StatCard label="Processing FPS" value={stats.processing_fps?.toFixed(1)} />
        <StatCard label="Detection latency" value={stats.detection_latency_ms?.toFixed(0)} unit="ms" />
        <StatCard label="Embedding latency" value={stats.embedding_latency_ms?.toFixed(0)} unit="ms" />
        <StatCard label="Frame queue" value={stats.queues?.frames} />
        <StatCard label="Persist queue" value={stats.queues?.persistence} />
      </div>

      <h2 className="section-title">System</h2>
      <div className="stat-grid">
        <StatCard label="CPU" value={stats.cpu_percent?.toFixed(0)} unit="%" tone={tone(stats.cpu_percent, 75, 90)} />
        <StatCard label="RAM" value={stats.ram_percent?.toFixed(0)} unit="%" tone={tone(stats.ram_percent, 75, 90)} />
        <StatCard label="RAM used" value={stats.ram_used_mb?.toFixed(0)} unit="MB" />
        <StatCard label="Disk used" value={stats.disk_percent?.toFixed(0)} unit="%" tone={tone(stats.disk_percent, 80, 92)} />
        <StatCard label="Disk free" value={stats.disk_free_gb?.toFixed(1)} unit="GB" />
        <StatCard
          label="Temperature"
          value={stats.temperature_c != null ? stats.temperature_c.toFixed(1) : "—"}
          unit="°C"
          tone={tone(stats.temperature_c ?? 0, 70, 80)}
        />
        {stats.npu_percent != null && (
          <StatCard
            label="NPU"
            value={stats.npu_percent.toFixed(0)}
            unit="%"
            tone="accent"
          />
        )}
        {stats.accelerator_temperature_c != null && (
          <StatCard
            label="Hailo-8 temp"
            value={stats.accelerator_temperature_c.toFixed(1)}
            unit="°C"
            tone={tone(stats.accelerator_temperature_c, 75, 85)}
          />
        )}
        <StatCard label="Uptime" value={formatUptime(stats.uptime_seconds)} />
      </div>
    </div>
  );
}
