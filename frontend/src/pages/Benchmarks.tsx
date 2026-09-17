import React from 'react'
import { useAsync } from '../components/ui'
import { api } from '../api'
import { PageHeader } from '../App'

export default function Benchmarks() {
  const [q, setQ] = React.useState('')
  const [cat, setCat] = React.useState('')
  const data = useAsync(() => api(`/api/v1/benchmarks?q=${encodeURIComponent(q)}&category=${encodeURIComponent(cat)}&limit=200`), [q, cat])
  const rows = data.data || []
  const categories = Array.from(new Set(rows.map((r: any) => r.category)))
  return (
    <div>
      <PageHeader title="Benchmarks" subtitle="Immutable, versioned task packages discovered from disk and synchronized into the database." />
      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <input className="input" placeholder="Search benchmarks" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input" value={cat} onChange={(e) => setCat(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <div className="flex items-center text-sm text-slate-500">{rows.length} benchmark versions</div>
      </div>
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="table">
          <thead><tr><th>Task</th><th>Version</th><th>Name</th><th>Category</th><th>Difficulty</th><th>Verifier</th><th>Hash</th></tr></thead>
          <tbody>
            {rows.map((b: any) => (
              <tr key={b.id}>
                <td className="font-mono text-xs">{b.task_id}</td>
                <td>{b.version}</td>
                <td>{b.name}</td>
                <td>{b.category}</td>
                <td>{b.difficulty}</td>
                <td>{b.manifest?.verifier}</td>
                <td className="font-mono text-xs text-slate-500">{b.content_hash.slice(0, 12)}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {rows.slice(0, 2).map((b: any) => (
          <div key={b.id} className="card">
            <div className="text-sm font-bold">{b.name}</div>
            <p className="mt-2 text-sm text-slate-600">{b.description}</p>
            <div className="mt-3 text-xs text-slate-500">Instruction preview: {String(b.instruction || '').slice(0, 180)}…</div>
          </div>
        ))}
      </div>
    </div>
  )
}