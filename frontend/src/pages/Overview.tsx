import React from 'react'
import { Link } from 'react-router-dom'
import { useAsync } from '../components/ui'
import { api, fmtPct } from '../api'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'

export default function Overview() {
  const system = useAsync(() => api('/api/v1/system'))
  const overview = useAsync(() => api('/api/v1/analytics/overview'))
  const experiments = useAsync(() => api('/api/v1/experiments'))
  const reports = useAsync(() => api('/api/v1/reports'))

  if (system.loading || overview.loading) return <div className="text-slate-500">Loading…</div>
  const s = system.data || {}
  const o = overview.data || {}
  const summary = o.summary || {}
  const overall = summary.overall || {}
  const agents = summary.per_agent || []
  const failure = Object.entries(overall.failure_distribution || {}).map(([name, value]) => ({ name, value }))
  const colors = ['#16a34a', '#dc2626', '#d97706', '#64748b', '#4f46e5', '#0ea5e9']

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-extrabold tracking-tight">Overview</h1>
        <p className="mt-1 text-sm text-slate-500">
          Live qualification metrics from deterministic local agents and real providers. Baseline scores are not LLM performance.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-6">
        {[
          ['Benchmarks', s.benchmarks, 'versioned tasks'],
          ['Agents', s.agents, 'versioned configs'],
          ['Experiments', s.experiments, 'tracked runs'],
          ['Trials', s.trials, `${s.passed_trials || 0} passed`],
          ['Reports', s.reports, 'release gates'],
          ['Known cost', `$${(s.known_cost_usd || 0).toFixed(4)}`, `${s.unknown_cost_trials || 0} unknown`],
        ].map(([label, value, hint]) => (
          <div key={label} className="card">
            <div className="label">{label}</div>
            <div className="mt-2 text-2xl font-extrabold">{value}</div>
            <div className="mt-1 text-xs text-slate-500">{hint}</div>
          </div>
        ))}
      </div>
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="card">
          <div className="mb-3 text-sm font-bold">Agent success rates</div>
          <div style={{ height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={agents.map((a: any) => ({ name: a.agent_name, rate: a.success_rate, ci: a.ci95 }))}>
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                <Tooltip formatter={(v: any) => `${(v * 100).toFixed(1)}%`} />
                <Bar dataKey="rate" fill="#4f46e5" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card">
          <div className="mb-3 text-sm font-bold">Failure distribution</div>
          <div style={{ height: 260 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={failure} dataKey="value" nameKey="name" outerRadius={95} innerRadius={50}>
                  {failure.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="card">
          <div className="mb-3 text-sm font-bold">Recent experiments</div>
          <div className="space-y-2">
            {(experiments.data || []).slice(0, 6).map((e: any) => (
              <Link key={e.id} to={`/experiments/${e.id}`} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2 hover:bg-slate-50">
                <div>
                  <div className="font-medium">{e.name}</div>
                  <div className="text-xs text-slate-500">{e.overall?.trials || 0} trials · {e.overall?.successes || 0} successes</div>
                </div>
                <span className="text-xs font-bold text-slate-500">{fmtPct(e.overall?.success_rate)}</span>
              </Link>
            ))}
          </div>
        </div>
        <div className="card">
          <div className="mb-3 text-sm font-bold">Recent reports</div>
          <div className="space-y-2">
            {(reports.data || []).slice(0, 6).map((r: any) => (
              <Link key={r.id} to="/reports" className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2 hover:bg-slate-50">
                <div>
                  <div className="font-medium">Report #{r.id}</div>
                  <div className="text-xs text-slate-500">Experiment {r.experiment_id}</div>
                </div>
                <span className={`pill ${r.gate === 'PASS' ? 'bg-emerald-100 text-emerald-700' : r.gate === 'FAIL' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{r.gate}</span>
              </Link>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
        {o.disclosure} Security boundaries are enforced by the tool layer and checked by independent verifiers.
      </div>
    </div>
  )
}