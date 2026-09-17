import React from 'react'
import { Link } from 'react-router-dom'
import { useAsync } from '../components/ui'
import { api } from '../api'
import { PageHeader } from '../App'

export default function Experiments() {
  const agents = useAsync(() => api('/api/v1/agents?limit=200'))
  const benches = useAsync(() => api('/api/v1/benchmarks?limit=200'))
  const experiments = useAsync(() => api('/api/v1/experiments?limit=100'))
  const [name, setName] = React.useState('')
  const [agentIds, setAgentIds] = React.useState<number[]>([])
  const [benchIds, setBenchIds] = React.useState<number[]>([])
  const [reps, setReps] = React.useState(1)
  const [creating, setCreating] = React.useState(false)

  async function create() {
    setCreating(true)
    try {
      const e = await api('/api/v1/experiments', {
        method: 'POST',
        body: JSON.stringify({ name: name || 'Untitled experiment', agent_ids: agentIds, benchmark_ids: benchIds, repetitions: reps }),
      })
      window.location.href = `/experiments/${e.id}`
    } finally { setCreating(false) }
  }

  function toggle(setter: any, id: number) {
    setter((prev: number[]) => prev.includes(id) ? prev.filter((x: number) => x !== id) : [...prev, id])
  }

  return (
    <div>
      <PageHeader title="Experiments" subtitle="Create and run controlled evaluations. Each trial gets a fresh workspace." />
      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <div className="card">
          <div className="mb-3 text-sm font-bold">Create experiment</div>
          <input className="input" placeholder="Experiment name" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <div className="label mb-2">Agents</div>
              <div className="max-h-40 space-y-1 overflow-auto">
                {(agents.data || []).filter((a: any) => !a.archived).map((a: any) => (
                  <label key={a.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={agentIds.includes(a.id)} onChange={() => toggle(setAgentIds, a.id)} />
                    {a.name} <span className="text-xs text-slate-400">({a.version})</span>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <div className="label mb-2">Benchmarks</div>
              <div className="max-h-40 space-y-1 overflow-auto">
                {(benches.data || []).filter((b: any) => !b.archived).map((b: any) => (
                  <label key={b.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={benchIds.includes(b.id)} onChange={() => toggle(setBenchIds, b.id)} />
                    {b.task_id} <span className="text-xs text-slate-400">({b.version})</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <input className="input w-24" type="number" min={1} max={20} value={reps} onChange={(e) => setReps(Number(e.target.value))} />
            <span className="text-xs text-slate-500">repetitions</span>
            <button className="btn ml-auto" disabled={!agentIds.length || !benchIds.length || creating} onClick={create}>
              {creating ? 'Creating…' : 'Create'}
            </button>
          </div>
        </div>
        <div className="card">
          <div className="mb-3 text-sm font-bold">Registered experiments</div>
          <div className="space-y-2 max-h-96 overflow-auto">
            {(experiments.data || []).map((e: any) => (
              <Link key={e.id} to={`/experiments/${e.id}`} className="block rounded-lg border border-slate-200 px-3 py-2 hover:bg-slate-50">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{e.name}</span>
                  <span className="text-xs text-slate-500">{e.status}</span>
                </div>
                <div className="text-xs text-slate-500">{e.overall?.trials || 0} trials · {e.overall?.successes || 0} successes · {e.agent_names?.join(', ')}</div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}