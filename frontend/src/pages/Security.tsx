import React from 'react'
import { useAsync } from '../components/ui'
import { api } from '../api'
import { PageHeader } from '../App'

export default function Security() {
  const [exp, setExp] = React.useState<number | ''>('')
  const experiments = useAsync(() => api('/api/v1/experiments?limit=200'))
  const data = useAsync(() => api(`/api/v1/analytics/security${exp ? `?experiment_id=${exp}` : ''}`), [exp])
  const d = data.data || {}
  return (
    <div>
      <PageHeader title="Security" subtitle="Synthetic secrets only. Boundaries are enforced by the tool layer and verified against output, not agent self-report." />
      <div className="mb-4 card">
        <select className="input" value={exp} onChange={(e) => setExp(e.target.value ? Number(e.target.value) : '')}>
          <option value="">All experiments</option>
          {(experiments.data || []).map((e: any) => <option key={e.id} value={e.id}>{e.id} · {e.name}</option>)}
        </select>
      </div>
      <div className="grid gap-4 md:grid-cols-4">
        <div className="card"><div className="label">Security trials</div><div className="mt-2 text-2xl font-extrabold">{d.security_trials}</div></div>
        <div className="card"><div className="label">Violations</div><div className="mt-2 text-2xl font-extrabold">{d.violations}</div></div>
        <div className="card"><div className="label">Passed</div><div className="mt-2 text-2xl font-extrabold">{d.passed}</div></div>
        <div className="card"><div className="label">Blocked attempts</div><div className="mt-2 text-2xl font-extrabold">{d.blocked_attempts}</div></div>
      </div>
      <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="table">
          <thead><tr><th>Trial</th><th>Agent</th><th>Task</th><th>Category</th><th>Reward</th><th>Blocked</th></tr></thead>
          <tbody>
            {(d.trials || []).map((t: any) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>{t.agent_name}</td>
                <td>{t.benchmark_task_id}</td>
                <td><span className="pill bg-red-100 text-red-700">{t.failure_category}</span></td>
                <td>{t.reward}</td>
                <td>{t.verifier_evidence?.permission_attempts_blocked?.length || 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">{d.boundary_note}</div>
    </div>
  )
}