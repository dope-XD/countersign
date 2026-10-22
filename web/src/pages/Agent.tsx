import { useCallback, useEffect, useRef, useState } from 'react'
import { api, wsUrl } from '../lib/api'
import { useEvents, usePoll } from '../lib/events'
import { PhoneAudio } from '../lib/phoneAudio'
import { ACTIONS, REQ_LABEL, clock, inr, maskPhone, type BankRequest, type Call, type Tier } from '../lib/types'
import { Dot, Spark, TierPill, TierText, TopBar } from '../components/ui'
import { useToast } from '../lib/useToast'

type LiveCall = { id: string; caller_cli: string; status: string; tier: Tier | null; language: string; source: string; started: number; customer_id: string | null }

const SCRIPT: Record<string, string> = {
  app_approval: "For your security, I've sent an approval request to the phone registered on this account.",
  liveness: 'For your security, please repeat a short phrase after me.',
  standard_checks: 'Could you confirm your date of birth and the last four digits of your card?',
  fraud_desk: "I'm transferring you to a colleague who can help with this request.",
}
const LANG: Record<string, string> = { hi: 'Hindi', en: 'English', hinglish: 'Hinglish', unknown: '—' }
const CUSTOMERS = [
  { id: 'rahul', name: 'Rahul Sharma' },
  { id: 'sunita', name: 'Sunita Sharma' },
]

const APPROVAL_TTL_S = 300 // must match engine/stepup/passkeys.py

/** App approval can be (re)sent: never sent, or the last one expired unanswered. */
function canSendApproval(r: BankRequest): boolean {
  const s = r.policy.reqs.app_approval
  if (!s || r.status !== 'open') return false
  return s.status === 'pending' || (s.status === 'sent' && Date.now() / 1000 - (s.at || 0) > APPROVAL_TTL_S)
}

export default function Agent() {
  const [callId, setCallId] = useState<string | null>(null)
  const [call, setCall] = useState<Call | null>(null)
  const [raw, setRaw] = useState(() => localStorage.getItem('cs.raw') === '1')
  const [audioOn, setAudioOn] = useState(false)
  const [, force] = useState(0)
  const { show, node: toast } = useToast()
  const calls = usePoll(() => api.get<LiveCall[]>('/api/calls'), 3000)
  const connected = useEvents(['calls'], () => calls.reload())
  const wsRef = useRef<WebSocket | null>(null)
  const audioRef = useRef<PhoneAudio | null>(null)

  useEffect(() => {
    const id = window.setInterval(() => force((x) => x + 1), 1000)
    return () => window.clearInterval(id)
  }, [])

  // per-call websocket: events + caller audio
  useEffect(() => {
    if (!callId) return
    const ws = new WebSocket(wsUrl(`/ws/agent/${callId}`))
    ws.binaryType = 'arraybuffer'
    ws.onmessage = (m) => {
      if (m.data instanceof ArrayBuffer) {
        audioRef.current?.play(m.data)
        return
      }
      const e = JSON.parse(m.data)
      if ((e.type === 'state' || e.type === 'ended') && e.call) setCall(e.call)
      if (e.type === 'liveness') show(e.result.passed ? 'Liveness check passed' : 'Liveness check failed')
    }
    wsRef.current = ws
    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [callId, show])

  const startAudio = async () => {
    const a = new PhoneAudio()
    a.onFrame = (b) => wsRef.current?.readyState === 1 && wsRef.current.send(b)
    try {
      await a.start({ kind: 'mic' })
      audioRef.current = a
      setAudioOn(true)
    } catch (e) {
      show('Microphone unavailable: ' + (e as Error).message, 'error')
    }
  }
  const stopAudio = async () => {
    await audioRef.current?.stop()
    audioRef.current = null
    setAudioOn(false)
  }
  useEffect(() => () => void audioRef.current?.stop(), [])

  const act = useCallback(
    async (fn: () => Promise<unknown>, ok?: string) => {
      try {
        await fn()
        if (ok) show(ok)
        if (callId) setCall(await api.get<Call>(`/api/calls/${callId}`))
      } catch (e) {
        show((e as Error).message, 'error')
      }
    },
    [callId, show],
  )

  const answer = async (id: string) => {
    await api.post(`/api/calls/${id}/answer`)
    setCallId(id)
    setCall(await api.get<Call>(`/api/calls/${id}`))
    calls.reload()
  }

  const toggleRaw = () => {
    localStorage.setItem('cs.raw', raw ? '0' : '1')
    setRaw(!raw)
  }

  const live = calls.data || []
  return (
    <div className="flex min-h-full flex-col">
      <TopBar
        title="Contact-centre agent"
        right={
          <>
            <span className="text-muted">Agent: Meera</span>
            <Dot ok={connected} />
            <button className="btn-ghost px-2 py-1 text-xs" onClick={toggleRaw}>
              {raw ? 'Hide' : 'Show'} demo internals
            </button>
          </>
        }
      />
      <div className="flex flex-1 flex-col lg:flex-row">
        <aside className="border-b border-line p-4 lg:w-72 lg:border-b-0 lg:border-r">
          <div className="label mb-2">Calls</div>
          {live.length === 0 && <p className="text-sm text-muted">Waiting for calls. Open /call on a phone to ring this console.</p>}
          <ul className="space-y-2">
            {live.map((c) => (
              <li key={c.id} className={`card p-3 ${c.id === callId ? 'border-brand' : ''}`}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm">{maskPhone(c.caller_cli)}</span>
                  <TierPill tier={c.tier} />
                </div>
                <div className="mt-1 flex items-center justify-between text-xs text-muted">
                  <span>
                    {LANG[c.language] || c.language} · {c.status}
                    {c.source === 'connect' && ' · Amazon Connect'}
                  </span>
                  {c.status === 'ringing' ? (
                    <button className="btn-primary px-3 py-1 text-xs" onClick={() => answer(c.id)}>
                      Answer
                    </button>
                  ) : c.id !== callId ? (
                    <button className="btn-outline px-3 py-1 text-xs" onClick={() => setCallId(c.id)}>
                      Open
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </aside>

        <main className="flex-1 p-4 sm:p-6">
          {!call ? (
            <div className="grid h-full place-items-center text-muted">No call open.</div>
          ) : (
            <CallView call={call} raw={raw} act={act} audioOn={audioOn} startAudio={startAudio} stopAudio={stopAudio} onClose={() => { setCallId(null); setCall(null) }} />
          )}
        </main>
      </div>
      {toast}
    </div>
  )
}

function CallView({ call, raw, act, audioOn, startAudio, stopAudio, onClose }: {
  call: Call
  raw: boolean
  act: (fn: () => Promise<unknown>, ok?: string) => Promise<void>
  audioOn: boolean
  startAudio: () => void
  stopAudio: () => void
  onClose: () => void
}) {
  const [action, setAction] = useState('change_mobile')
  const [details, setDetails] = useState<Record<string, string>>({})
  const v = call.verdict
  const tier = call.tier
  const elapsed = call.status === 'ended' ? call.elapsed : Date.now() / 1000 - call.started
  const openReqs = call.requests.filter((r) => r.status === 'open')
  const nextReq = openReqs.flatMap((r) => r.missing)[0]
  const script = tier === 'RED' && openReqs.some((r) => r.policy.risk === 'high') ? SCRIPT.app_approval : nextReq ? SCRIPT[nextReq] : null
  const updated = v ? Math.max(0, Math.round(Date.now() / 1000 - v.updated)) : null
  const highRed = tier === 'RED'

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="card flex flex-wrap items-center justify-between gap-2 bg-[#ECEAE4] px-4 py-2 text-sm">
        <span>
          Call {clock(elapsed)} · <span className="font-mono">{maskPhone(call.caller_cli)}</span> · {LANG[call.language] || call.language}
          {call.source === 'connect' && (
            <span className="ml-2 text-xs text-muted">
              Amazon Connect{call.media_delay_s != null && ` · audio ${call.media_delay_s.toFixed(1)} s behind`}
            </span>
          )}
          {call.status === 'ended' && <span className="ml-2 font-semibold text-red">ended</span>}
        </span>
        <span className="flex items-center gap-2">
          {call.status !== 'ended' &&
            call.source !== 'connect' &&
            (audioOn ? (
              <button className="btn-ghost px-2 py-1 text-xs" onClick={stopAudio}>Headset off</button>
            ) : (
              <button className="btn-outline px-3 py-1 text-xs" onClick={startAudio}>Connect headset</button>
            ))}
          {call.status !== 'ended' ? (
            <button className="btn-ghost px-2 py-1 text-xs text-red" onClick={() => act(() => api.post(`/api/calls/${call.id}/hangup`))}>
              {call.source === 'connect' ? 'Stop listening' : 'End call'}
            </button>
          ) : (
            <button className="btn-ghost px-2 py-1 text-xs" onClick={onClose}>Close</button>
          )}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
        {/* ---------------- left: customer + requests */}
        <div className="space-y-4">
          <section className="card p-4">
            <div className="label">Customer</div>
            <div className="mt-2 flex items-center gap-2">
              <select className="input" value={call.customer?.id || ''} onChange={(e) => act(() => api.post(`/api/calls/${call.id}/identify`, { customer_id: e.target.value }))}>
                <option value="" disabled>Identify the customer…</option>
                {CUSTOMERS.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            {call.customer && (
              <dl className="mt-3 grid grid-cols-2 gap-y-1 text-sm">
                <dt className="text-muted">Account</dt>
                <dd className="font-mono">••••{call.customer.account_no.slice(-4)}</dd>
                <dt className="text-muted">Registered mobile</dt>
                <dd className="font-mono">{maskPhone(call.customer.registered_mobile)}</dd>
                <dt className="text-muted">City</dt>
                <dd>{call.customer.city}</dd>
              </dl>
            )}
          </section>

          <section className="card p-4">
            <div className="label">Caller wants to</div>
            <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto]">
              <select className="input" value={action} onChange={(e) => { setAction(e.target.value); setDetails({}) }}>
                {Object.entries(ACTIONS).map(([k, a]) => (
                  <option key={k} value={k}>{a.label} ({a.risk})</option>
                ))}
              </select>
              <button className="btn-primary" disabled={!call.customer || call.status === 'ended'} onClick={() => act(() => api.post(`/api/calls/${call.id}/request`, { action, details }), 'Request logged')}>
                Log request
              </button>
            </div>
            {ACTIONS[action].fields?.map((f) => (
              <input key={f.key} className="input mt-2" placeholder={f.label + (f.placeholder ? ` (${f.placeholder})` : '')} value={details[f.key] || ''} onChange={(e) => setDetails({ ...details, [f.key]: e.target.value })} />
            ))}
          </section>

          {call.requests.map((r) => (
            <RequestCard key={r.id} r={r} call={call} act={act} />
          ))}
        </div>

        {/* ---------------- right: Voice Trust Card */}
        <div className="space-y-4">
          <section className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-line bg-[#ECEAE4] px-4 py-2 text-xs text-muted">
              <span>Voice Trust Card</span>
              <span>{call.customer ? call.customer.name : 'customer not identified'}</span>
            </div>
            <div className="p-5">
              <div className="text-sm text-muted">Caller wants to</div>
              <div className="font-display text-xl font-bold">
                {openReqs.length ? ACTIONS[openReqs[openReqs.length - 1].action]?.label : call.requests.length ? ACTIONS[call.requests[call.requests.length - 1].action]?.label : '—'}
              </div>
              <hr className="my-4 border-line" />
              <div className="flex items-baseline gap-3">
                <TierText tier={tier} className="font-display text-4xl font-extrabold" />
                <span className="text-sm text-muted">voice risk{updated !== null ? `, updated ${updated} s ago` : ', listening for the first 8 s of speech'}</span>
              </div>
              {v && v.reasons.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {v.reasons.map((code, i) => (
                    <li key={code} className="text-sm">
                      <span className="code mr-2 text-ink">{code}</span>
                      <span className="text-muted">{v.reason_text[i]}</span>
                    </li>
                  ))}
                </ul>
              )}
              {openReqs.some((r) => r.policy.no_sensitive_details) && (
                <p className="mt-3 rounded-md bg-red-soft px-3 py-2 text-sm text-red">Do not read out any account details on this call.</p>
              )}
              {script && (
                <div className="mt-4 rounded-md bg-[#ECEAE4] px-3 py-2 text-sm">
                  Say: “{script}”
                </div>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  className="btn-primary"
                  disabled={!openReqs.some(canSendApproval)}
                  onClick={() => {
                    const r = openReqs.find(canSendApproval)
                    if (r) act(() => api.post(`/api/requests/${r.id}/send-approval`), 'Approval sent to the registered phone')
                  }}
                >
                  Send app approval
                </button>
                <button className="btn-outline" disabled={call.status === 'ended' && !!call.case_id} onClick={() => act(() => api.post(`/api/calls/${call.id}/transfer`), 'Case sent to the fraud desk')}>
                  Transfer to fraud desk
                </button>
                <button
                  className="btn-outline"
                  disabled={highRed || !openReqs.some((r) => ['liveness', 'standard_checks'].some((k) => r.policy.reqs[k]?.status === 'pending'))}
                  onClick={() => {
                    const r = openReqs.find((x) => x.policy.reqs.liveness?.status === 'pending' || x.policy.reqs.standard_checks?.status === 'pending')
                    if (!r) return
                    const reqName = r.policy.reqs.liveness?.status === 'pending' ? 'liveness' : 'standard_checks'
                    const reason = prompt(`Override ${REQ_LABEL[reqName]}: reason (logged)`)
                    if (reason) act(() => api.post(`/api/requests/${r.id}/override`, { requirement: reqName, reason, agent: 'meera' }), 'Override logged')
                  }}
                >
                  Override
                </button>
              </div>
              {highRed && <p className="mt-2 text-xs text-muted">Override is not available on RED.</p>}
            </div>
          </section>

          <LivenessPanel call={call} act={act} />

          {raw && <RawPanel call={call} />}
        </div>
      </div>
    </div>
  )
}

function LivenessPanel({ call, act }: { call: Call; act: (fn: () => Promise<unknown>, ok?: string) => Promise<void> }) {
  const ch = call.challenge
  const l = call.liveness
  return (
    <section className="card p-4">
      <div className="flex items-center justify-between">
        <div className="label">Liveness check</div>
        <button className="btn-outline px-3 py-1 text-xs" disabled={call.status !== 'live' || (!!ch && !ch.done)} onClick={() => act(() => api.post(`/api/calls/${call.id}/challenge`))}>
          {ch ? 'New challenge' : 'Start liveness check'}
        </button>
      </div>
      {ch && !ch.done && (
        <div className="mt-3 space-y-2">
          <p className="rounded-md bg-brand-soft px-3 py-3 text-lg font-semibold text-brand">{ch.say}</p>
          <p className="text-xs text-muted">Read it aloud now. We time the caller's reply from the moment you stop speaking.</p>
          <button className="btn-ghost px-0 py-0 text-xs underline" onClick={() => act(() => api.post(`/api/calls/${call.id}/challenge/done-reading`))}>
            I’ve finished reading (no headset)
          </button>
        </div>
      )}
      {ch && !ch.done && <p className="mt-2 text-xs text-muted">Listening for the reply…</p>}
      {l && (
        <div className={`mt-3 rounded-md px-3 py-2 text-sm ${l.passed ? 'bg-green-soft text-green' : 'bg-red-soft text-red'}`}>
          {l.passed ? 'Passed' : 'Failed'}
          {l.lag_s !== null && <> · replied after {l.lag_s.toFixed(1)} s</>}
          {l.reasons.length > 0 && <span className="code ml-2">{l.reasons.join(' ')}</span>}
        </div>
      )}
    </section>
  )
}

function RequestCard({ r, call, act }: { r: BankRequest; call: Call; act: (fn: () => Promise<unknown>, ok?: string) => Promise<void> }) {
  const miss = r.missing
  const label = ACTIONS[r.action]?.label || r.action
  const statusTone = r.status === 'executed' ? 'text-green' : r.status === 'open' ? 'text-ink' : 'text-red'
  return (
    <section className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{label}</div>
          <div className="text-xs text-muted">
            {r.policy.risk} risk · decided at <TierText tier={r.policy.tier} className="font-semibold" /> · {Object.entries(r.details).map(([k, v]) => `${k.replace('_', ' ')} ${k === 'amount' ? inr(Number(v)) : v}`).join(', ')}
          </div>
        </div>
        <span className={`text-xs font-semibold uppercase ${statusTone}`}>{r.status}</span>
      </div>
      <p className="mt-2 text-sm text-muted">{r.policy.note}</p>
      {r.policy.no_phone_approval && <p className="mt-1 text-xs font-semibold text-red">No approval by phone on this request.</p>}
      <ul className="mt-3 space-y-2">
        {Object.entries(r.policy.reqs).map(([k, s]) => {
          const done = ['met', 'waived', 'replaced'].includes(s.status) || (k === 'cooloff_24h' && !miss.includes(k))
          const failed = s.status === 'failed'
          return (
            <li key={k} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="flex items-center gap-2">
                <span className={`grid h-5 w-5 place-items-center rounded-full text-[11px] ${done ? 'bg-green text-white' : failed ? 'bg-red text-white' : 'border border-line'}`}>
                  {done ? '✓' : failed ? '✕' : ''}
                </span>
                {REQ_LABEL[k] || k}
                <span className="text-xs text-muted">
                  {s.status === 'sent' && (canSendApproval(r) ? 'no answer, approval expired' : 'waiting for the customer…')}
                  {s.status === 'waived' && 'overridden'}
                  {s.status === 'replaced' && 'replaced by app approval'}
                  {k === 'cooloff_24h' && (s.until ? `until ${new Date(s.until * 1000).toLocaleString()}` : 'starts after app approval')}
                  {failed && (k === 'app_approval' ? 'customer said no' : 'failed')}
                </span>
              </span>
              {r.status === 'open' && (
                <span className="flex gap-1">
                  {k === 'standard_checks' && s.status === 'pending' && (
                    <>
                      <button className="btn-outline px-2 py-1 text-xs" onClick={() => act(() => api.post(`/api/requests/${r.id}/standard-checks`, { passed: true }))}>Passed</button>
                      <button className="btn-ghost px-2 py-1 text-xs" onClick={() => act(() => api.post(`/api/requests/${r.id}/standard-checks`, { passed: false }))}>Failed</button>
                    </>
                  )}
                  {k === 'liveness' && s.status === 'pending' && (
                    <button className="btn-ghost px-2 py-1 text-xs" onClick={() => act(() => api.post(`/api/requests/${r.id}/decline-voice-check`), 'Switched to app approval')}>Customer declines voice check</button>
                  )}
                  {k === 'app_approval' && canSendApproval(r) && (
                    <button className="btn-primary px-2 py-1 text-xs" onClick={() => act(() => api.post(`/api/requests/${r.id}/send-approval`), 'Approval sent')}>
                      {s.status === 'sent' ? 'Resend' : 'Send'}
                    </button>
                  )}
                  {k === 'fraud_desk' && s.status === 'pending' && !call.case_id && (
                    <button className="btn-outline px-2 py-1 text-xs" onClick={() => act(() => api.post(`/api/calls/${call.id}/transfer`), 'Sent to fraud desk')}>Transfer</button>
                  )}
                </span>
              )}
            </li>
          )
        })}
      </ul>
      {r.status === 'open' && (
        <div className="mt-4 flex items-center justify-between gap-2 border-t border-line pt-3">
          <span className="text-xs text-muted">{miss.length ? `Waiting on: ${miss.map((m) => REQ_LABEL[m] || m).join(', ')}` : 'All checks complete.'}</span>
          <button className="btn-primary" disabled={miss.length > 0} onClick={() => act(() => api.post(`/api/requests/${r.id}/execute`), 'Change made')}>
            Make the change
          </button>
        </div>
      )}
    </section>
  )
}

function RawPanel({ call }: { call: Call }) {
  const v = call.verdict
  return (
    <section className="card border-dashed p-4">
      <div className="label">Demo internals — agents never see raw scores</div>
      <div className="mt-2 text-xs text-muted">
        S1 backend <span className="code">{call.model.s1}</span> ({call.model.version}) · S2 {call.model.s2 ? 'ECAPA' : 'off'}
        {call.first_tier_at !== null && <> · first tier at {call.first_tier_at.toFixed(1)} s</>}
      </div>
      <div className="mt-3">
        <div className="text-xs text-muted">S1 P(synthetic) per 4 s window</div>
        <Spark values={call.windows.map((w) => w.p)} height={60} />
      </div>
      {v && (
        <dl className="mt-3 grid grid-cols-3 gap-2 font-mono text-xs">
          <div><dt className="text-muted">r</dt><dd>{v.r.toFixed(3)}</dd></div>
          <div><dt className="text-muted">S1 call</dt><dd>{v.features.s1.toFixed(3)}</dd></div>
          <div><dt className="text-muted">S2 drift</dt><dd>{v.features.drift === null ? '—' : v.features.drift.toFixed(3)}</dd></div>
          <div><dt className="text-muted">voice tier</dt><dd>{v.voice_tier}</dd></div>
          <div><dt className="text-muted">context</dt><dd>{v.context.flags.join(' ') || 'none'}</dd></div>
          <div><dt className="text-muted">windows</dt><dd>{v.features.windows}</dd></div>
        </dl>
      )}
      <div className="mt-3 max-h-40 overflow-auto font-mono text-[11px] text-muted">
        {call.timeline.map((e, i) => (
          <div key={i}>{e.t.toFixed(1)}s {e.event} {JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k]) => !['t', 'event'].includes(k))))}</div>
        ))}
      </div>
    </section>
  )
}
