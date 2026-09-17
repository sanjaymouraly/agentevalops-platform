import React from 'react'
import { useAsync } from '../components/ui'
import { api } from '../api'
import { PageHeader } from '../App'

export default function Agents() {
  const agents = useAsync(() => api('/api/v1/agents?limit=200'))
  const rows = agents.data || []
  return (
    <div>
      <PageHeader title="Agents" subtitle="Versioned agent configurations. LLM agents require a real provider and fail honestly if one is not configured." />
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="table">
          <thead><tr><th>Name</th><th>Version</th><th>Kind</th><th>Provider / model</th><th>Tools</th><th>Description</th></tr></thead>
          <tbody>
            {rows.map((a: any) => (
              <tr key={a.id}>
                <td className="font-medium">{a.name}</td>
                <td>{a.version}</td>
                <td><span className="pill bg-indigo-100 text-indigo-700">{a.kind}</span></td>
                <td>{a.provider} / {a.model}</td>
                <td className="text-xs">{(a.tools || []).join(', ')}</td>
                <td className="text-xs text-slate-600">{a.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}