import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Settings,
  ScrollText,
  Cpu,
  Wifi,
  WifiOff,
  Zap,
} from 'lucide-react';
import useKriyaStream from './hooks/useKriyaStream';
import Overview  from './pages/Overview';
import SettingsPage from './pages/Settings';
import Logs      from './pages/Logs';

// ── Phase badge colours ───────────────────────────────────────────────────────
const PHASE_STYLES = {
  SENSE:  'bg-sky-900   text-sky-300   border-sky-700',
  REASON: 'bg-amber-900 text-amber-300 border-amber-700',
  ACT:    'bg-emerald-900 text-emerald-300 border-emerald-700',
  IDLE:   'bg-zinc-800  text-zinc-400   border-zinc-700',
};

const NAV_ITEMS = [
  { to: '/overview',  label: 'Overview',  Icon: LayoutDashboard },
  { to: '/settings',  label: 'Settings',  Icon: Settings         },
  { to: '/logs',      label: 'Logs',      Icon: ScrollText        },
];

function Sidebar({ phase, connected }) {
  const phaseStyle = PHASE_STYLES[phase] ?? PHASE_STYLES.IDLE;

  return (
    <aside className="
      w-[250px] min-h-screen flex-shrink-0
      bg-zinc-950 border-r border-zinc-800
      flex flex-col
    ">
      {/* ── Logo ── */}
      <div className="px-5 pt-6 pb-4 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <Zap size={18} className="text-cyan-400" />
          <span className="font-mono text-sm font-semibold tracking-widest text-zinc-100 uppercase">
            YantraOS
          </span>
        </div>
        <p className="font-mono text-[10px] text-zinc-600 tracking-widest mt-1 uppercase">
          Command Centre v3
        </p>
      </div>

      {/* ── Nav ── */}
      <nav className="flex-1 px-2 py-4 flex flex-col gap-0.5">
        {NAV_ITEMS.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-sm font-mono transition-colors
              border border-transparent
              ${isActive
                ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
                : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200'
              }`
            }
          >
            <Icon size={15} />
            <span className="tracking-wider uppercase text-[11px]">{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* ── Status Footer ── */}
      <div className="px-4 py-4 border-t border-zinc-800 space-y-3">
        {/* Phase indicator */}
        <div className={`flex items-center justify-between px-2 py-1.5 border font-mono text-[10px] tracking-widest uppercase ${phaseStyle}`}>
          <span>Phase</span>
          <span className={`font-bold ${phase === 'REASON' ? 'animate-pulse' : ''}`}>
            {phase}
          </span>
        </div>

        {/* Connection indicator */}
        <div className="flex items-center gap-2">
          {connected
            ? <Wifi size={12} className="text-emerald-400" />
            : <WifiOff size={12} className="text-red-500" />
          }
          <span className={`font-mono text-[10px] uppercase tracking-widest ${connected ? 'text-emerald-500' : 'text-red-500'}`}>
            {connected ? 'Stream Live' : 'Reconnecting…'}
          </span>
        </div>
      </div>
    </aside>
  );
}

export default function App() {
  const stream = useKriyaStream();

  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-zinc-950 text-zinc-300">
        <Sidebar phase={stream.phase} connected={stream.connected} />

        {/* ── Main content ── */}
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/"         element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<Overview  stream={stream} />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/logs"     element={<Logs stream={stream} />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
