import { NavLink, Route, Routes } from "react-router-dom";
import { useEventState } from "./lib/useEvents.js";
import LivePage from "./pages/LivePage.jsx";
import RecentPage from "./pages/RecentPage.jsx";
import FaceDetailPage from "./pages/FaceDetailPage.jsx";
import SearchPage from "./pages/SearchPage.jsx";
import StatsPage from "./pages/StatsPage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";

const NAV = [
  { to: "/", label: "Live View", icon: "📹" },
  { to: "/recent", label: "Recent Captures", icon: "🧑" },
  { to: "/search", label: "Search", icon: "🔍" },
  { to: "/stats", label: "Statistics", icon: "📊" },
  { to: "/settings", label: "Settings", icon: "⚙️" },
];

export default function App() {
  const status = useEventState("live_status");
  const connected = status?.camera_connected ?? false;

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">◉</span>
          <div>
            <div className="brand-name">Edge Face Capture</div>
            <div className="brand-sub">Raspberry Pi CM5</div>
          </div>
        </div>
        <nav>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className={`dot ${connected ? "dot-ok" : "dot-bad"}`} />
          {connected ? "Camera online" : "Camera offline"}
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<LivePage />} />
          <Route path="/recent" element={<RecentPage />} />
          <Route path="/faces/:id" element={<FaceDetailPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
