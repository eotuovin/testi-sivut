export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
    this.detail = detail
  }
}

async function request<T>(method: string, path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  const url = new URL('/api' + path, window.location.origin)
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v))
  }
  const init: RequestInit = { method, credentials: 'same-origin', headers: {} }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
  }
  const res = await fetch(url.toString(), init)
  if (res.status === 401 && !path.startsWith('/login')) {
    window.dispatchEvent(new CustomEvent('luuri:unauthenticated'))
  }
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* non-json error body */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const apiGet = <T>(path: string, params?: Record<string, unknown>) => request<T>('GET', path, undefined, params)
export const apiPost = <T>(path: string, body?: unknown, params?: Record<string, unknown>) => request<T>('POST', path, body, params)
export const apiPatch = <T>(path: string, body?: unknown) => request<T>('PATCH', path, body)
export const apiPut = <T>(path: string, body?: unknown) => request<T>('PUT', path, body)
export const apiDelete = <T>(path: string) => request<T>('DELETE', path)

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { message?: string } | string
    if (typeof d === 'string') return d
    if (d && typeof d === 'object' && 'message' in d && d.message) return d.message
    return e.message
  }
  return e instanceof Error ? e.message : String(e)
}
