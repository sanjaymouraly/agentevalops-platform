import React from 'react'
import { useAsync } from '../components/ui'
import { api } from '../api'
import { PageHeader } from '../App'

export default function Compare() {
  const experiments = useAsync(() => api('/api/v1/experiments?limit=200'))
  const [baseline, setBaseline] = React.useState<number | null>(null)
  const [candidate, setCandidate] = React.useState<number | null>(null)
  const [result, setResult] = React.useState<any>(null)
  const [loading, setLoading] = React.useState(false)

  async function compare() {
    if (!baseline || !candidate) return
    setLoading(true)
    try { setResult(await api(`/api/v1/experiments/${candidate}/compare?baseline_id=${baseline}`)) }
    finally { setLoading(false) }
  }

  return (
    <div>
      <PageHeader title="Comparison & regression" subtitle="Matched (agent, benchmark) cells with explicit thresholds and coverage." />
      <div className="mb-4 card">
        <div className="grid gap-3 md:grid-cols-3">
          <select className="input" onChange={(e) => setBaseline(Number(e.target.value))}>
            <option value="">Baseline experiment</option>
            {(experiments.data || []).map((e: any) => <option key={e.id} value={e.id}>{e.id} · {e.name}</option>)}
          </select>
          <select className="input" onChange={(e) => setCandidate(Number(e.target.value))}>
            <option value="">Candidate experiment</option>
            {(experiments.data || []).map((e: any) => <option key={e.id} value={e.id}>{e.id} · {e.name}</option>)}
          </select>
          <button className="btn" disabled={!baseline || !candidate || loading} onClick={compare}>{loading ? 'Comparing…' : 'Compare'}</button>
        </div>
      </div>
      {result && (
        <>
          <div className="mb-4 card">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div><div className="label">Matched cells</div><div className="mt-1 text-2xl font-extrabold">{result.coverage.matched_cells}</div></div>
              <div><div className="label">Regressions</div><div className="mt-1 text-2xl font-extrabold">{result.regressions.length}</div></div>
              <div><div className="label">Baseline success</div><div className="mt-1 text-2xl font-extrabold">{(result.baseline_overall.success_rate * 100).toFixed(0)}%</div></div>
              <div><div className="label">Candidate success</div><div className="mt-1 text-2xl font-extrabold">{(result.candidate_overall.success_rate * 100).toFixed(0)}%</div></div>
            </div>
            <div className="mt-3 text-xs text-slate-500">{result.methodology}</div>
          </div>
          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <table className="table">
              <thead><tr><th>Type</th><th>Agent</th><th>Benchmark</th><th>Baseline</th><th>Candidate</th><th>Detail</th></tr></thead>
              <tbody>
                {result.regressions.length === 0 && <tr><td colSpan={6} className="text-center text-slate-500">No regressions detected.</td></tr>}
                {result.regressions.map((r: any, i: number) => (
                  <tr key={i}>
                    <td><span className="pill bg-red-100 text-red-700">{r.type}</span></td>
                    <td>{r.agent}</td>
                    <td>{r.benchmark_id}</td>
                    <td>{r.baseline}</td>
                    <td>{r.candidate}</td>
                    <td className="text-xs">{r.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.coverage.unmatched_candidate_agents?.length > 0 && (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Unmatched candidate agents: {result.coverage.unmatched_candidate_agents.join(', ')}. They are reported, not compared as if they were the same system.
            </div>
          )}
        </>
      )}
    </div>
  )
}