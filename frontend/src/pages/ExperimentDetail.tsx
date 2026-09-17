import React from 'react'
import { useParams } from 'react-router-dom'
import { useAsync } from '../components/ui'
import { api } from '../api'
import { PageHeader } from '../App'
import { Pill } from '../components/ui'

export default function ExperimentDetail() {
  const { id } = useParams()
  const detail = useAsync(() => api(`/api/v1/experiments/${id}`), [id])
  const [running, setRunning] = React.useState(false)
  const [report, setReport] = React.useState<any>(null)

  async function run() {
    setRunning(true)
    try {
      const r = await api(`/api/v1/experiments/${id}/run`, { method: 'POST' })
      detail.data = r
    } finally { setRunning(false) }
  }
  async function cancel() {
    await api(`/api/v1/experiments/${id}/cancel`, { method: 'POST' })
    detail.data = await api(`/api/v1/experiments/${id}`)
  }
  async function makeReport() {
    const r = await api(`/api/v1/experiments/${id}/report`, { method: 'POST', body: JSON.stringify({}) })
    setReport(r)
  }

  if (detail.loading) return <div>Loading…</div>
  const d = detail.data || {}
  const trials = d.trials || []
  return (
    <div>
      <PageHeader title={d.name} subtitle={d.description} action={
        <div className="flex gap-2">
          <button className="btn" disabled={running || d.status === 'running'} onClick={run}>{running ? 'Running…' : 'Run'}</button>
          <button className="btn-secondary" onClick={cancel}>Cancel</button>
          <button className="btn-secondary" onClick={makeReport}>Generate report</button>
        </div>
      } />
      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        <span className="pill bg-slate-100 text-slate-700">Status: {d.status}</span>
        <span className="pill bg-slate-100 text-slate-700">Trials: {d.summary?.overall?.trials || 0}</span>
        <span className="pill bg-slate-100 text-slate-700">Success: {((d.summary?.overall?.success_rate || 0) * 100).toFixed(0)}%</span>
        <span className="pill bg-slate-100 text-slate-700">Security violations: {d.summary?.overall?.failure_distribution?.security_violation || 0}</span>
      </div>
      {report && (
        <div className="mb-4 card">
          <div className="flex items-center justify-between">
            <span>Report #{report.report_id} gate <Pill value={report.gate} /></span>
            <a className="btn-secondary" href={`/api/v1/reports/${report.report_id}/download?fmt=pdf`} target="_blank" rel="noreferrer">Download PDF</a>
          </div>
        </div>
      )}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="table">
          <thead><tr><th>Agent</th><th>Task</th><th>Rep</th><th>Status</th><th>Reward</th><th>Failure</th><th>Latency</th><th>Tokens</th></tr></thead>
          <tbody>
            {trials.map((t: any) => (
              <tr key={t.id}>
                <td>{t.agent_name} <span className="text-xs text-slate-400">{t.agent_version}</span></td>
                <td>{t.benchmark_task_id}</td>
                <td>{t.repetition}</td>
                <td><Pill value={t.status} /></td>
                <td>{t.reward ?? '—'}</td>
                <td>{t.failure_category}</td>
                <td>{t.latency_ms ? `${Math.round(t.latency_ms)} ms` : '—'}</td>
                <td className="text-xs">{t.input_tokens || 0}/{t.output_tokens || 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}