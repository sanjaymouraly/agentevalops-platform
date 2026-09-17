import React from 'react'
import { useAsync } from '../components/ui'
import { api } from '../api'
import { PageHeader } from '../App'

export default function Providers() {
  const providers = useAsync(() => api('/api/v1/providers'))
  const data = providers.data || {}
  return (
    <div>
      <PageHeader title="Providers" subtitle="OpenAI, Claude, OpenRouter, Gemini, Azure, Ollama, vLLM, custom endpoints, and mock wiring. Keys are never persisted." />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <div className="mb-3 text-sm font-bold">Configured providers</div>
          <div className="space-y-2">
            {(data.configured || []).map((p: any) => (
              <div key={p.id} className="rounded-lg border border-slate-200 px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{p.name}</span>
                  <span className="text-xs text-slate-500">{p.provider_type}</span>
                </div>
                <div className="mt-1 text-xs text-slate-500">{p.model || 'no model'} · key {p.api_key_masked || 'none'}</div>
              </div>
            ))}
            {!(data.configured || []).length && <div className="text-sm text-slate-500">No persisted provider configs. Use Ollama locally.</div>}
          </div>
        </div>
        <div className="card">
          <div className="mb-3 text-sm font-bold">Supported provider types</div>
          <div className="grid grid-cols-2 gap-2">
            {(data.catalog || []).map((p: any) => (
              <div key={p.type} className="rounded-lg border border-slate-200 px-3 py-2">
                <div className="font-medium">{p.label}</div>
                <div className="text-xs text-slate-500">{p.note}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-4 card">
        <div className="mb-2 text-sm font-bold">Environment variables present</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(data.env_vars_present || {}).map(([k, v]) => (
            <span key={k} className={`pill ${v ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{k}: {String(v)}</span>
          ))}
        </div>
      </div>
    </div>
  )
}