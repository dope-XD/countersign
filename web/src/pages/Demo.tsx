import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { api } from '../lib/api'
import { usePoll } from '../lib/events'
import type { Customer } from '../lib/types'
import { TopBar } from '../components/ui'
import { useToast } from '../lib/useToast'

type World = {
  customers: Record<string, Customer>
  fri: Record<string, string>
  sim_swaps: Record<string, number>
  recent_calls: Record<string, number>
  on_call?: Record<string, { kind: string; direction: string; since: number }>
}
type Stored = {
  voiceprints: number
  calls_with_speaker_embeddings_in_memory: number
  audio_files_on_disk: { file: string; bytes: number; encrypted: boolean }[]
  live_audio_seconds_in_memory: Record<string, number>
  case_rows: { id: string; tier: string; reasons: string[]; status: string; outcome: string | null }[]
  audit_events: number
  transcripts_stored: number
}
type Health = { models: Record<string, string>; s1_version: string; p95_ms: number | null; live_calls: number; public_url?: string }

function QR({ path, label, base }: { path: string; label: string; base: string }) {
  const [src, setSrc] = useState('')
  const url = `${base}${path}`
  useEffect(() => {
    QRCode.toDataURL(url, { margin: 1, width: 180 }).then(setSrc)
  }, [url])
  return (
    <a href={path} target="_blank" rel="noreferrer" className="card block p-3 text-center no-underline">
      {src && <img src={src} alt={`QR code for ${label}`} className="mx-auto h-36 w-36" />}
      <div className="mt-2 text-sm font-semibold text-ink">{label}</div>
      <div className="truncate font-mono text-[11px] text-muted">{path}</div>
    </a>
  )
}

export default function Demo() {
  const world = usePoll(() => api.get<World>('/api/demo/world'), 4000)
  const stored = usePoll(() => api.get<Stored>('/api/demo/stored'), 3000)
  const health = usePoll(() => api.get<Health>('/api/health'), 5000)
  const { show, node: toast } = useToast()
  const w = world.data
  const insecure = location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1'

  const call = async (p: string, body: unknown, msg: string) => {
    try {
      await api.post(p, body)
      show(msg)
      world.reload()
      stored.reload()
    } catch (e) {
      show((e as Error).message, 'error')
    }
  }

  const base = health.data?.public_url || location.origin
  const rahul = w?.customers.rahul
  const swapOn = rahul ? rahul.registered_mobile in (w?.sim_swaps || {}) : false
  const onCall = Object.entries(w?.on_call || {})

  return (
    <div className="min-h-full">
      <TopBar title="Demo operator" />
      <main className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
        {insecure && (
          <p className="rounded-md bg-amber-soft p-3 text-sm">
            This page is on plain HTTP over the network. Open it through the HTTPS tunnel (see docs/RUNBOOK.md) so the QR code points phones at the right address.
          </p>
        )}
        <section className="card flex flex-wrap items-center gap-4 p-4">
          <div className="w-40">
            <QR path="/download/cs-bank.apk" label="CS Bank for Android" base={base} />
          </div>
          <div className="max-w-xl text-sm">
            <div className="text-lg font-bold">For judges</div>
            <p className="mt-1">
              Scan, install, sign up. Each phone gets its own account with ₹2,50,000. Make a family with the judge next to you, call the bank from the app (an AI agent
              answers), try to break into each other's accounts, or have someone call you pretending to be family and try to pay them.
            </p>
            <p className="mt-2 text-xs text-muted">Team phones: in the app, choose “Team demo account” and enter the staff PIN to take Rahul or Sunita.</p>
          </div>
        </section>

        <section>
          <h2 className="text-xl font-bold">Staff pages</h2>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <QR path="/agent" label="Agent console" base={base} />
            <QR path="/fraud" label="Fraud desk" base={base} />
            <QR path="/metrics" label="Metrics" base={base} />
            <QR path="/call" label="Backup softphone" base={base} />
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          <div className="card space-y-3 p-4">
            <div className="label">Scenario controls</div>
            <button className="btn-danger w-full" onClick={() => confirm('Reset requests, cases and calls? Accounts opened in the app and their phones are kept.') && call('/api/demo/reset', {}, 'World reset')}>
              Reset demo world
            </button>
            <div className="text-xs text-muted">
              On a call now (from the CS Bank app):{' '}
              {onCall.length ? onCall.map(([c, s]) => <span key={c} className="mr-2">{w?.customers[c]?.name || c} ({s.kind}, {s.direction})</span>) : 'nobody'}
            </div>
            <button className="btn-outline w-full" onClick={() => call('/api/demo/sim-swap', { customer_id: 'rahul', on: !swapOn, hours_ago: 5 }, swapOn ? 'SIM swap cleared' : 'SIM swap on Rahul’s number 5 h ago')}>
              {swapOn ? 'Clear' : 'Simulate'} SIM swap on Rahul’s number
            </button>
            <div className="text-xs text-muted">
              FRI-rated numbers:{' '}
              {Object.entries(w?.fri || {}).map(([k, v]) => (
                <span key={k} className="mr-2 font-mono">{k} ({v})</span>
              ))}
            </div>
          </div>

          <div className="card p-4">
            <div className="label">Engine</div>
            {health.data ? (
              <dl className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between"><dt className="text-muted">S1</dt><dd className="font-mono">{health.data.models.s1} · {health.data.s1_version}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">S2</dt><dd className="font-mono">{health.data.models.s2}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">ASR</dt><dd className="font-mono">{health.data.models.asr}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">p95 per window</dt><dd className="font-mono">{health.data.p95_ms ? `${health.data.p95_ms.toFixed(0)} ms` : '—'}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Live calls</dt><dd className="font-mono">{health.data.live_calls}</dd></div>
              </dl>
            ) : (
              <p className="text-sm text-red">Engine not reachable.</p>
            )}
            {health.data?.models.s1 === 'dummy' && <p className="mt-2 rounded bg-amber-soft p-2 text-xs">S1 is the placeholder scorer. Run ml/port_sls_checkpoint.py to load the real detector.</p>}
          </div>

          <div className="card p-4">
            <div className="label">What Countersign holds right now</div>
            {stored.data && (
              <dl className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between"><dt>Voiceprints</dt><dd className="font-semibold">{stored.data.voiceprints}</dd></div>
                <div className="flex justify-between"><dt>Call transcripts</dt><dd className="font-semibold">{stored.data.transcripts_stored}</dd></div>
                <div className="flex justify-between"><dt>Calls with audio in memory</dt><dd className="font-semibold">{Object.values(stored.data.live_audio_seconds_in_memory).filter((s) => s > 0).length}</dd></div>
                <div className="flex justify-between"><dt>Audio files on disk</dt><dd className="font-semibold">{stored.data.audio_files_on_disk.length} {stored.data.audio_files_on_disk.length > 0 && '(RED clips, encrypted)'}</dd></div>
                <div className="flex justify-between"><dt>Case rows (scores, reasons)</dt><dd className="font-semibold">{stored.data.case_rows.length}</dd></div>
                <div className="flex justify-between"><dt>Audit events</dt><dd className="font-semibold">{stored.data.audit_events}</dd></div>
              </dl>
            )}
          </div>
        </section>
      </main>
      {toast}
    </div>
  )
}
