import { useEffect, useRef, useState } from 'react'
import { wsUrl } from './api'

export type Ev = { topic: string; type: string; ts: number; [k: string]: unknown }

/** Subscribe to engine events; reconnects on drop and sends a heartbeat every 10 s. */
export function useEvents(topics: string[], onEvent: (e: Ev) => void) {
  const cb = useRef(onEvent)
  cb.current = onEvent
  const [connected, setConnected] = useState(false)
  const key = topics.join(',')
  useEffect(() => {
    if (!key) return
    let ws: WebSocket | null = null
    let closed = false
    let beat: number | undefined
    let retry: number | undefined
    const open = () => {
      ws = new WebSocket(wsUrl(`/ws/events?topics=${encodeURIComponent(key)}`))
      ws.onopen = () => {
        setConnected(true)
        ws?.send('hi')
        beat = window.setInterval(() => ws?.readyState === 1 && ws.send('hb'), 10000)
      }
      ws.onmessage = (m) => cb.current(JSON.parse(m.data))
      ws.onclose = () => {
        setConnected(false)
        window.clearInterval(beat)
        if (!closed) retry = window.setTimeout(open, 1500)
      }
    }
    open()
    return () => {
      closed = true
      window.clearInterval(beat)
      window.clearTimeout(retry)
      ws?.close()
    }
  }, [key])
  return connected
}

export function usePoll<T>(fn: () => Promise<T>, ms: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const tick = useRef(0)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const reload = () => {
    const t = ++tick.current
    fnRef
      .current()
      .then((d) => {
        if (t === tick.current) {
          setData(d)
          setError(null)
        }
      })
      .catch((e) => setError(String(e?.message || e)))
  }
  useEffect(() => {
    reload()
    if (!ms) return
    const id = window.setInterval(reload, ms)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error, reload, setData }
}
