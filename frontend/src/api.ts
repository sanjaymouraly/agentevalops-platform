export const getKey = () => localStorage.getItem('aeo_key') || 'dev-admin-key-change-me'
export function setKey(v: string) { localStorage.setItem('aeo_key', v) }
export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', 'X-API-Key': getKey(), ...(opts.headers || {}) },
  })
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 320)}`)
  if (r.status === 204) return undefined as T
  return r.json()
}
export const fmtPct = (x: number | null | undefined) => x == null ? '—' : `${(x * 100).toFixed(0)}%`
export const fmtNum = (x: number | null | undefined) => x == null ? '—' : new Intl.NumberFormat().format(x)
export const fmtMoney = (x: number | null | undefined) => x == null ? '—' : `$${x.toFixed(4)}`