export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData
  const res = await fetch(path, {
    method,
    headers: isForm || body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: isForm ? (body as FormData) : body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!res.ok) {
    const d = data as { error?: string; detail?: string } | null
    throw new ApiError(res.status, d?.error || d?.detail || res.statusText)
  }
  return data as T
}

export const api = {
  get: <T,>(p: string) => req<T>('GET', p),
  post: <T,>(p: string, b?: unknown) => req<T>('POST', p, b ?? {}),
  del: <T,>(p: string) => req<T>('DELETE', p),
  upload: <T,>(p: string, f: File | Blob, name = 'file') => {
    const fd = new FormData()
    fd.append(name, f, (f as File).name || 'voice-note')
    return req<T>('POST', p, fd)
  },
}

export function wsUrl(path: string) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}${path}`
}
