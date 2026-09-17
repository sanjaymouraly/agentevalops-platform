import React from 'react'
import { useAsync } from '../components/ui'
import { api } from '../api'
import { PageHeader } from '../App'

export default function Failures() {
  const [exp, setExp] = React.useState<number | ''>('')
  const experiments = useAsync(() => api('/api/v1/experiments?limit=200'))
  const failures = useAsync(() => api(`/api/v1/analytics/failures${exp ? `?experiment_id=${exp}` : ''}`), [exp])
  const data = failures.data || {}
  return (
    <div>
      <PageHeader title="Failures" subtitle="Evidence-based failure taxonomy and reviewer corrections." />
      <div className="mb-4 card">
        <select className="input" value={exp} onChange={(e) => setExp(e.target.value ? Number(e.target.value) : '')}>
          <option value="">All experiments</option>
          {(experiments.data || []).map((e: any) => <option key={e.id} value={e.id}>{e.id} · {e.name}</option>)}
        </select>
      </div>
      <div className="mb-4 grid gap-4 md:grid-cols-3">
        {Object.entries(data.distribution || {}).map(([k, v]) => (
          <div key={k} className="card"><div className="label">{k}</div><div className="mt-2 text-2xl font-extrabold">{v as any}</div></div>
        ))}
      </div>
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="table">
          <thead><tr><th>Trial</th><th>Agent</th><th>Task</th><th>Category</th><th>Reward</th><th>Detail</th></tr></thead>
          <tbody>
            {(data.trials || []).map((t: any) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>{t.agent_name}</td>
                <td>{t.benchmark_task_id}</td>
                <td><span className="pill bg-red-100 text-red-700">{t.failure_category}</span></td>
                <td>{t.reward}</td>
                <td className="text-xs">{t.failure_detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}