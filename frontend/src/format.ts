const dt = new Intl.DateTimeFormat('fi-FI', { dateStyle: 'short', timeStyle: 'short' })
const d = new Intl.DateTimeFormat('fi-FI', { dateStyle: 'short' })

export function fmtDateTime(iso: string | null | undefined): string {
  return iso ? dt.format(new Date(iso)) : '—'
}
export function fmtDate(iso: string | null | undefined): string {
  return iso ? d.format(new Date(iso)) : '—'
}
export function fmtMinutes(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  return `${Math.round(seconds / 60)} min`
}
export function fmtEur(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return new Intl.NumberFormat('fi-FI', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(Number(v))
}
