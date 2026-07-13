export default function StatCard({ label, value, unit, tone = "default" }) {
  return (
    <div className={`stat-card stat-${tone}`}>
      <div className="stat-value">
        {value}
        {unit && <span className="stat-unit">{unit}</span>}
      </div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
