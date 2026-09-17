import React from 'react'
import { useAsync } from '../components/ui'
import { api } from '../api'
import { PageHeader } from '../App'

export default function Reports() {
  const reports = useAsync(() => api('/api/v1/reports?limit=100'))
  const [selected, setSelected] = React.useState<number | null>(null)
  const detail = useAsync(() => selected ? api(`/api/v1/reports/${selected}`) : Promise.resolve(null), [selected])
  const [decision, setDecision] = React.useState('rejected')
  const [override, setOverride] = React.useState(false)
  const [justification, setJustification] = React.useState('')
  const [status, setStatus] = React.useState('')

  async function approve() {
    if (!selected) return
    try {
      await api(`/api/v1/reports/${selected}/approve`, {
        method: 'POST',
        body: JSON.stringify({ decision, override_gate: override, justification, approver: 'dashboard-approver' }),
      })
      setStatus('Decision recorded.')
      detail.data = await api(`/api/v1/reports/${selected}`)
      reports.data = await api('/api/v1/reports?limit=100')
    } catch (e: any) { setStatus(e.message) }
  }

  return (
    <div>
      <PageHeader title="Reports & approvals" subtitle="Human approval is separate from the automated gate. A failing gate needs an explicit justified override." />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <div className="mb-3 text-sm font-bold">Reports</div>
          <div className="space-y-2 max-h-96 overflow-auto">
            {(reports.data || []).map((r: any) => (
              <button key={r.id} onClick={() => setSelected(r.id)} className={`block w-full rounded-lg border px-3 py-2 text-left ${selected === r.id ? 'border-indigo-500 bg-indigo-50' : 'border-slate-200 hover:bg-slate-50'}`}>
                <div className="flex items-center justify-between">
                  <span className="font-medium">Report #{r.id} · Exp {r.experiment_id}</span>
                  <span className={`pill ${r.gate === 'PASS' ? 'bg-emerald-100 text-emerald-700' : r.gate === 'FAIL' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{r.gate}</span>
                </div>
                <div className="text-xs text-slate-500">{new Date(r.created_at).toLocaleString()}</div>
              </button>
            ))}
          </div>
        </div>
        <div className="card">
          {detail.data ? (
            <>
              <div className="mb-3 text-sm font-bold">Report #{detail.data.id}</div>
              <div className="mb-3 text-sm">Gate: <span className={`pill ${detail.data.gate === 'PASS' ? 'bg-emerald-100 text-emerald-700' : detail.data.gate === 'FAIL' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{detail.data.gate}</span></div>
              <div className="mb-3 flex gap-2">
                {['markdown', 'html', 'json', 'pdf'].map((fmt) => (
                  <a key={fmt} className="btn-secondary" href={`/api/v1/reports/${detail.data.id}/download?fmt=${fmt}`} target="_blank" rel="noreferrer">{fmt}</a>
                ))}
              </div>
              <div className="mb-3 space-y-2">
                {(detail.data.approvals || []).map((a: any) => (
                  <div key={a.id} className="rounded-lg border border-slate-200 px-3 py-2 text-sm">
                    {a.decision} by {a.approver} ({a.role}) {a.override_gate ? '— override' : ''}
                  </div>
                ))}
              </div>
              <div className="grid gap-2">
                <select className="input" value={decision} onChange={(e) => setDecision(e.target.value)}>
                  <option value="approved">approved</option>
                  <option value="rejected">rejected</option>
                </select>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> Override non-PASS gate
                </label>
                <textarea className="input" placeholder="Justification (required for override)" value={justification} onChange={(e) => setJustification(e.target.value)} />
                <button className="btn" onClick={approve}>Record decision</button>
                {status && <div className="text-sm text-slate-600">{status}</div>}
              </div>
            </>
          ) : <div className="text-sm text-slate-500">Select a report.</div>}
        </div>
      </div>
    </div>
  )
}