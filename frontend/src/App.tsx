import { Link, NavLink, Outlet } from 'react-router-dom'
import { LayoutDashboard, FlaskConical, Boxes, Bot, Shield, BarChart3, FileCheck, Plug, Settings } from 'lucide-react'

const nav = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/experiments', label: 'Experiments', icon: FlaskConical },
  { to: '/benchmarks', label: 'Benchmarks', icon: Boxes },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/providers', label: 'Providers', icon: Plug },
  { to: '/compare', label: 'Comparison', icon: BarChart3 },
  { to: '/failures', label: 'Failures', icon: Shield },
  { to: '/security', label: 'Security', icon: Shield },
  { to: '/reports', label: 'Reports', icon: FileCheck },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export default function App() {
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 h-screen w-64 border-r border-slate-200 bg-slate-950 px-4 py-5 text-slate-200">
        <div className="px-2">
          <div className="text-lg font-extrabold text-white">AgentEvalOps</div>
          <div className="mt-1 text-xs text-slate-400">Continuous AI agent qualification</div>
        </div>
        <nav className="mt-6 space-y-1">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive ? 'bg-indigo-600 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}>
              <Icon size={17} /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute bottom-5 left-4 right-4 text-xs text-slate-500">
          Qualification is not a production deployment authorization.
        </div>
      </aside>
      <main className="flex-1 px-6 py-6 lg:px-10">
        <Outlet />
      </main>
    </div>
  )
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}