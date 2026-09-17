import React from 'react'
import { api } from '../api'

export function useAsync<T>(fn: () => Promise<T>, deps: any[] = []) {
  const [state, setState] = React.useState<{ loading: boolean; data: T | null; error: string | null }>({
    loading: true, data: null, error: null,
  })
  React.useEffect(() => {
    let alive = true
    setState({ loading: true, data: state.data, error: null })
    fn().then((data) => alive && setState({ loading: false, data, error: null }))
      .catch((e) => alive && setState({ loading: false, data: null, error: String(e) }))
    return () => { alive = false }
  }, deps)
  return state
}

export function Pill({ value }: { value: string }) {
  const color =
    value === 'PASS' || value === 'completed' || value === 'approved' ? 'bg-emerald-100 text-emerald-700' :
    value === 'FAIL' || value === 'failed' || value === 'rejected' || value === 'security_violation' ? 'bg-red-100 text-red-700' :
    value === 'running' || value === 'queued' || value === 'pending' ? 'bg-amber-100 text-amber-700' :
    value === 'INSUFFICIENT_EVIDENCE' ? 'bg-orange-100 text-orange-700' :
    'bg-slate-100 text-slate-700'
  return <span className={`pill ${color}`}>{value}</span>
}

export function Card({ title, children, className = '' }: any) {
  return <div className={`card ${className}`}><div className="mb-3 text-sm font-bold text-slate-700">{title}</div>{children}</div>
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null
  return <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
}

export function Empty({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">{text}</div>
}

export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className="mt-2 text-3xl font-extrabold text-slate-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

export { api }