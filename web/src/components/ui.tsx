import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Tier } from '../lib/types'

const TIER_STYLE: Record<Tier, string> = {
  GREEN: 'text-green bg-green-soft',
  AMBER: 'text-amber bg-amber-soft',
  RED: 'text-red bg-red-soft',
}

export function TierText({ tier, className = '' }: { tier: Tier | null; className?: string }) {
  if (!tier) return <span className={`text-muted ${className}`}>LISTENING</span>
  const color = tier === 'GREEN' ? 'text-green' : tier === 'AMBER' ? 'text-amber' : 'text-red'
  return <span className={`${color} ${className}`}>{tier}</span>
}

export function TierPill({ tier }: { tier: Tier | null }) {
  if (!tier) return <span className="rounded-full bg-line/60 px-2 py-0.5 font-mono text-[11px] text-muted">…</span>
  return <span className={`rounded-full px-2 py-0.5 font-mono text-[11px] font-medium ${TIER_STYLE[tier]}`}>{tier}</span>
}

export function Signature({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 120 30" className={className} aria-hidden>
      <path d="M2 24c6-20 10-20 14 0s8 20 14 0 9-20 15 0 9 10 15-4" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

export function TopBar({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <header className="flex items-center justify-between border-b border-line bg-paper/90 px-4 py-3 backdrop-blur sm:px-6">
      <Link to="/" className="flex items-center gap-2 text-ink no-underline">
        <Signature className="h-5 w-12 text-brand" />
        <span className="font-display text-lg font-bold">Countersign</span>
        <span className="hidden text-sm text-muted sm:inline">· {title}</span>
      </Link>
      <div className="flex items-center gap-3 text-sm">{right}</div>
    </header>
  )
}

export function Dot({ ok }: { ok: boolean }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${ok ? 'bg-green' : 'bg-red'}`} title={ok ? 'connected' : 'disconnected'} />
}

export function Toast({ msg, onDone, tone = 'info' }: { msg: string | null; onDone: () => void; tone?: 'info' | 'error' }) {
  useEffect(() => {
    if (!msg) return
    const id = window.setTimeout(onDone, 4500)
    return () => window.clearTimeout(id)
  }, [msg, onDone])
  if (!msg) return null
  return (
    <div className={`fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-md px-4 py-2 text-sm text-white shadow-lg ${tone === 'error' ? 'bg-red' : 'bg-ink'}`}>
      {msg}
    </div>
  )
}

export function useToast() {
  const [msg, setMsg] = useState<string | null>(null)
  const [tone, setTone] = useState<'info' | 'error'>('info')
  // stable identity: pages use `show` in effect dependencies
  const show = useCallback((m: string, t: 'info' | 'error' = 'info') => {
    setTone(t)
    setMsg(m)
  }, [])
  const done = useCallback(() => setMsg(null), [])
  const node = <Toast msg={msg} tone={tone} onDone={done} />
  return { show, node }
}

export function Spark({ values, height = 40, threshold = [0.3, 0.7] }: { values: number[]; height?: number; threshold?: number[] }) {
  const w = 240
  if (!values.length) return <div className="text-xs text-muted">no windows yet</div>
  const step = values.length > 1 ? w / (values.length - 1) : w
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(height - v * height).toFixed(1)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
      {threshold.map((t) => (
        <line key={t} x1={0} x2={w} y1={height - t * height} y2={height - t * height} stroke="#D9D6CE" strokeDasharray="3 3" />
      ))}
      <polyline points={pts} fill="none" stroke="#1F3F94" strokeWidth={2} />
    </svg>
  )
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="label">{label}</span>
      {children}
    </label>
  )
}
