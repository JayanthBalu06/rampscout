/** Thin fetch wrapper. All requests carry the demo-session cookie. */
export type Decimal = string

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  })
  const body = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) {
    const err = body?.error ?? {}
    throw new ApiError(res.status, err.code ?? 'http_error', err.message ?? res.statusText, err.details)
  }
  return body as T
}

export interface Health {
  status: string
  db: string
  demo_mode: boolean
}
