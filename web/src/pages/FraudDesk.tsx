import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useEvents, usePoll } from '../lib/events'
import { ACTIONS, ago, inr, type BankRequest, type Tier } from '../lib/types'
import { Dot, TierPill, TopBar } from '../components/ui'
import { useToast } from '../lib/useToast'

type CaseRow = {
  id: string
  call_id: string | null
  request_id: string | null
  customer_id: string | null
  channel: string
  opened_at: number
  status: string
  tier: Tier | null
  reasons: string[]
  scores: Record<string, unknown>
  model_version: string | null
  timeline: { t: number; event: string; [k: string]: unknown }[]
  outcome: string | null
}
type CaseDetail = CaseRow & {
  audit: { ts: number; actor: string; event: string; detail: unknown }[]
  request: BankRequest | null
  reports: { id: string; kind: string; payload: Record<string, unknown> }[]
  has_clip: boolean
}

const SLA = 15 * 60

export default function FraudDesk() {
  const cases = usePoll(() => api.get<CaseRow[]>('/api/cases'), 5000)
  const [sel, setSel] = useState<string | null>(null)
  const connected = useEvents(['desk'], () => {
    cases.reload()
    if (sel) loadDetail(sel)
  })
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [clipUrl, setClipUrl] = useState<string | null>(null)
  const [, tick] = useState(0)
  const { show, node: toast } = useToast()

  useEffect(() => {
    const id = window.setInterval(() => tick((x) => x + 1), 1000)
    return () => window.clearInterval(id)
  }, [])

  const loadDetail = async (id: string) => setDetail(await api.get<CaseDetail>(`/api/cases/${id}`))
  useEffect(() => {
    setClipUrl(null)
    if (sel) loadDetail(sel)
  }, [sel])
  // free the decrypted clip from memory when it is replaced or the page closes
  useEffect(() => () => {
    if (clipUrl) URL.revokeObjectURL(clipUrl)
  }, [clipUrl])

  const play = async () => {
    if (!detail) return
    const res = await fetch(`/api/cases/${detail.id}/clip?analyst=priya`)
    if (!res.ok) return show('No clip available', 'error')
    setClipUrl(URL.createObjectURL(await res.blob()))
    loadDetail(detail.id)
  }

  const resolve = async (outcome: string) => {
    if (!detail) return
    const note = outcome === 'false_alarm' ? prompt('Note for the weekly review (optional)') || '' : ''
    await api.post(`/api/cases/${detail.id}/resolve`, { outcome, analyst: 'priya', note })
    show(outcome === 'fraud_confirmed' ? 'Fraud confirmed. 1930 report and DoT DIP share created.' : outcome === 'false_alarm' ? 'Released. Customer told why.' : 'Callback scheduled')
    loadDetail(detail.id)
    cases.reload()
  }

  const rows = cases.data || []
  return (
    <div className="flex min-h-full flex-col">
      <TopBar title="Fraud desk" right={<><span className="text-muted">Analyst: Priya</span><Dot ok={connected} /></>} />
      <div className="flex flex-1 flex-col lg:flex-row">
        <aside className="border-b border-line lg:w-96 lg:border-b-0 lg:border-r">
          <div className="label px-4 pt-4">Case queue</div>
          {rows.length === 0 && <p className="p-4 text-sm text-muted">No cases. RED calls and declined approvals land here.</p>}
          <ul>
            {rows.map((c) => {
              const left = SLA - (Date.now() / 1000 - c.opened_at)
              return (
                <li key={c.id}>
                  <button className={`w-full border-b border-line px-4 py-3 text-left hover:bg-card ${sel === c.id ? 'bg-card' : ''}`} onClick={() => setSel(c.id)}>
                    <div className="flex items-center justify-between">
                      <span className="font-semibold capitalize">{c.customer_id || 'unknown'}</span>
                      <TierPill tier={c.tier} />
                    </div>
                    <div className="mt-1 flex items-center justify-between text-xs text-muted">
                      <span>{c.channel === 'app' ? 'Bank app' : 'Contact centre'} · {ago(c.opened_at)}</span>
                      <span className={c.status === 'open' && left < 300 ? 'text-red' : ''}>{c.status === 'open' ? (left > 0 ? `${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, '0')} to decide` : 'SLA passed') : c.outcome?.replace('_', ' ')}</span>
                    </div>
                    <div className="mt-1 font-mono text-[11px] text-muted">{(c.reasons || []).join(' ')}</div>
                  </button>
                </li>
              )
            })}
          </ul>
        </aside>
        <main className="flex-1 p-4 sm:p-6">
          {!detail ? (
            <div className="grid h-full place-items-center text-muted">Select a case.</div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-4">
              <section className="card p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-2xl font-bold capitalize">{detail.customer_id || 'Unknown customer'}</h2>
                  <TierPill tier={detail.tier} />
                </div>
                <p className="text-sm text-muted">{detail.channel === 'app' ? 'Bank app' : 'Contact centre call'} · opened {new Date(detail.opened_at * 1000).toLocaleTimeString()} · model {detail.model_version || '—'}</p>
                {detail.request && (
                  <p className="mt-3 text-sm">
                    Held request: <b>{ACTIONS[detail.request.action]?.label || (detail.request.action === 'upi_payment' ? 'UPI payment' : detail.request.action)}</b>
                    {detail.request.details?.amount ? ` · ${inr(Number(detail.request.details.amount))}` : ''} · <span className="uppercase">{detail.request.status}</span>
                  </p>
                )}
                <ul className="mt-3 space-y-1">
                  {(detail.reasons || []).map((r) => (
                    <li key={r} className="code">{r}</li>
                  ))}
                </ul>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {detail.has_clip ? (
                    <button className="btn-outline" onClick={play}>Play 20 s evidence clip</button>
                  ) : (
                    <span className="text-xs text-muted">No audio kept for this case.</span>
                  )}
                  {clipUrl && <audio src={clipUrl} controls autoPlay className="h-8" />}
                </div>
                {detail.has_clip && <p className="mt-1 text-xs text-muted">Encrypted at rest. Every play is logged. Deleted after 30 days or when the case closes.</p>}
              </section>

              {detail.status === 'open' && (
                <section className="card flex flex-wrap gap-2 p-4">
                  <button className="btn-danger" onClick={() => resolve('fraud_confirmed')}>Confirm fraud</button>
                  <button className="btn-outline" onClick={() => resolve('false_alarm')}>False alarm, release</button>
                  <button className="btn-ghost" onClick={() => resolve('callback')}>Call back on registered number</button>
                </section>
              )}

              {detail.reports.length > 0 && (
                <section className="card p-4">
                  <div className="label">Reports filed</div>
                  <ul className="mt-2 space-y-1 text-sm">
                    {detail.reports.map((r) => (
                      <li key={r.id}>
                        <span className="code mr-2">{r.kind === 'ncrp_1930' ? 'NCRP / 1930' : r.kind === 'dot_dip' ? 'DoT DIP' : r.kind}</span>
                        <span className="text-muted">{JSON.stringify(r.payload)}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section className="card p-4">
                <div className="label">Timeline</div>
                <ol className="mt-2 space-y-1 text-sm">
                  {detail.timeline.map((e, i) => (
                    <li key={i} className="flex gap-3">
                      <span className="w-20 shrink-0 font-mono text-xs text-muted">{new Date(e.t * 1000).toLocaleTimeString()}</span>
                      <span>{e.event.replace(/_/g, ' ')}</span>
                    </li>
                  ))}
                </ol>
              </section>

              <section className="card p-4">
                <div className="label">Audit log</div>
                <ol className="mt-2 max-h-64 space-y-1 overflow-auto font-mono text-[11px]">
                  {detail.audit.map((e, i) => (
                    <li key={i}>
                      {new Date(e.ts * 1000).toLocaleTimeString()} <b>{e.actor}</b> {e.event} {e.detail ? JSON.stringify(e.detail) : ''}
                    </li>
                  ))}
                </ol>
              </section>
            </div>
          )}
        </main>
      </div>
      {toast}
    </div>
  )
}
