import { BrowserRouter, Navigate, NavLink, Route, Routes } from 'react-router-dom'
import Gate from './components/Gate'
import { LogoMark } from './components/Logo'
import Calendar from './pages/Calendar'
import Dashboard from './pages/Dashboard'
import Review from './pages/Review'
import Settings from './pages/Settings'

const NAV = [
  { to: '/calendar', label: 'Content Calendar', icon: '🗓' },
  { to: '/review', label: 'Review Queue', icon: '✍' },
  { to: '/dashboard', label: 'Dashboard', icon: '📊' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
]

export default function App() {
  return (
    <Gate>
    <BrowserRouter>
      <div className="app">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">
              <LogoMark size={28} />
            </span>
            <div>
              <div className="brand-title">GenFlows</div>
              <div className="brand-sub">LinkedIn Automation</div>
            </div>
          </div>

          <nav className="nav">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
              >
                <span className="nav-num">{n.icon}</span>
                <span className="nav-label">{n.label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="sidebar-foot">
            <span className="dot live" />
            Autonomous · weekly batches
          </div>
        </aside>

        <main className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/calendar" replace />} />
            <Route path="/calendar" element={<Calendar />} />
            <Route path="/review" element={<Review />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/calendar" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
    </Gate>
  )
}
