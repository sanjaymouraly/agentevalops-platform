import React from 'react'
import { useAsync } from '../components/ui'
import { api, getKey, setKey } from '../api'
import { PageHeader } from '../App'

export default function Settings() {
  const [key, setKeyValue] = React.useState(getKey())
  const worker = useAsync(() => api('/api/v1/worker/status'))
  const usage = useAsync(() => api('/api/v1/usage'))
  const [cleanup, setCleanup] = React.useState<any>(null)
  async function runCleanup() {
    setCleanup(await api('/api/v1/admin/cleanup', { method: 'POST', body: JSON.stringify({ older_than_days: 30, dry_run: true }) }))
  }
  return (
    <div>
      <PageHeader title="Settings & operations" subtitle="API key, worker status, retention and usage. Production must disable anonymous access." />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <div className="mb-3 text-sm font-bold">API key</div>
          <input className="input" value={key} onChange={(e) => setKeyValue(e.target.value)} />
          <button className="btn mt-2" onClick={() => setKey(key)}>Save to browser</button>
          <p className="mt-2 text-xs text-slate-500">The key is stored in localStorage for this browser only. Server-side RBAC uses server-configured keys.</p>
        </div>
        <div className="card">
          <div className="mb-3 text-sm font-bold">Worker status</div>
          {worker.data && (
            <div className="space-y-1 text-sm">
              <div>Mode: {worker.data.execution_mode}</div>
              <div>Queue depth: {worker.data.queue_depth}</div>
              <div>Concurrency: {worker.data.max_concurrency}</div>
              <div>Docker: {String(worker.data.docker_available)} / runner {String(worker.data.docker_runner_image_available)}</div>
              <div>Harbor: {String(worker.data.harbor_available)}</div>
            </div>
          )}
        </div>
        <div className="card">
          <div className="mb-3 text-sm font-bold">Usage</div>
          {usage.data && (
            <div className="space-y-1 text-sm">
              <div>Known cost: ${usage.data.known_cost_usd}</div>
              <div>Unknown-cost trials: {usage.data.unknown_cost_trials}</div>
              <div>Input tokens: {usage.data.input_tokens}</div>
              <div>Output tokens: {usage.data.output_tokens}</div>
            </div>
          )}
        </div>
        <div className="card">
          <div className="mb-3 text-sm font-bold">Retention (dry run)</div>
          <button className="btn-secondary" onClick={runCleanup}>Run dry-run cleanup</button>
          {cleanup && <div className="mt-2 text-sm text-slate-600">Candidates: {cleanup.candidates.length}, bytes: {cleanup.candidate_bytes}</div>}
        </div>
      </div>
    </div>
  )
}