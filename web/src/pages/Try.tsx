import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { browserSupportsWebAuthn, startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { api, wsUrl } from '../lib/api'
import { useEvents } from '../lib/events'
import { PhoneAudio } from '../lib/phoneAudio'
import { clock, inr, type Approval, type Call, type Customer, type Tier } from '../lib/types'
import { Spark, TierPill, TopBar } from '../components/ui'
import { useToast } from '../lib/useToast'
import { deviceLabel, inAndroidApp } from '../lib/device'
import { ApprovalSheet, CallAlerts } from './Bank'

type Home = { customer: Customer; passkeys: { id: string }[]; pending: Approval[] }
type Sample = { id: string; label: string }
type Line = { who: 'bank' | 'you'; text: string }
type Result = { outcome: 'executed' | 'declined' | 'held' | 'unfinished'; tier: Tier | null }
type CallView = { state: 'connecting' | 'live' | 'ended'; started: number; voice: string; lines: Line[]; challenge: string | null; call: Call | null; result: Result | null }

const KEY = 'cs.try.customer'
const OUTCOME: Record<Result['outcome'], { title: string; tone: string }> = {
  executed: { title: 'Change made, with one tap on your phone', tone: 'bg-green-soft text-green' },
  declined: { title: 'Stopped. Nothing changed, fraud case opened', tone: 'bg-red-soft text-red' },
  held: { title: 'Blocked on the call: 24 h hold and the fraud desk', tone: 'bg-amber-soft text-ink' },
  unfinished: { title: 'Nothing changed', tone: 'bg-line text-ink' },
}

function load(k: string): string | null {
  try {
    return localStorage.getItem(k)
  } catch {
    return null
  }
}
function save(k: string, v: string) {
  try {
    localStorage.setItem(k, v)
  } catch {
    /* private mode: the account just won't survive a reload */
  }
}

/** Speak the virtual agent's line on this phone. Resolves when it has finished (or would have). */
function speak(text: string): Promise<void> {
  const fallback = () => new Promise<void>((r) => window.setTimeout(r, Math.min(9000, 400 + text.split(' ').length * 320)))
  if (!('speechSynthesis' in window)) return fallback()
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text.replace(/"/g, ''))
    u.lang = 'en-IN'
    u.rate = 1.05
    let done = false
    const finish = () => {
      if (!done) {
        done = true
        resolve()
      }
    }
    u.onend = finish
    u.onerror = finish
    window.setTimeout(finish, 15000) // some phones never fire onend
    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(u)
  })
}

/**
 * /try: a judge's own demo account and a call to the bank, answered by a virtual agent.
 * Everything except the agent is the real engine (scoring, policy, passkeys, cases).
 */
export default function Try() {
  const [home, setHome] = useState<Home | null>(null)
  const [samples, setSamples] = useState<Sample[]>([])
  const [apk, setApk] = useState(false)
  const [view, setView] = useState<CallView | null>(null)
  const [approval, setApproval] = useState<Approval | null>(null)
  const [busy, setBusy] = useState(false)
  const [, tick] = useState(0)
  const { show, node: toast } = useToast()
  const ws = useRef<WebSocket | null>(null)
  const audio = useRef<PhoneAudio | null>(null)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const clip = useRef<Sample | null>(null) // the cloned voice this call will play instead of the mic
  const playing = useRef(false) // a clip call: no mic, so nothing to mute

  const refresh = useCallback(async (cid: string) => {
    const h = await api.get<Home>(`/api/app/${cid}/home`)
    setHome(h)
    setApproval((cur) => cur ?? h.pending[0] ?? null)
    return h
  }, [])

  // this phone's sandbox account: reuse it, or make a new one
  useEffect(() => {
    ;(async () => {
      const known = load(KEY)
      try {
        if (known) {
          await refresh(known)
          return
        }
      } catch {
        /* gone (or another phone's): make a new one */
      }
      try {
        const { customer } = await api.post<{ customer: Customer }>('/api/try/start')
        save(KEY, customer.id)
        await refresh(customer.id)
      } catch (e) {
        show((e as Error).message, 'error')
      }
    })()
    api.get<{ samples: Sample[]; apk: boolean }>('/api/try/info').then((i) => {
      setSamples(i.samples)
      setApk(i.apk)
    }, () => {})
    const id = window.setInterval(() => tick((x) => x + 1), 1000)
    return () => window.clearInterval(id)
  }, [refresh, show])

  const cid = home?.customer.id
  useEvents(cid ? [`app:${cid}`] : [], (e) => {
    if (e.type === 'approval') {
      setApproval(e.approval as Approval)
      if (navigator.vibrate) navigator.vibrate([200, 100, 200])
    }
  })

  /** The attacker's clip starts once the agent has finished greeting, like a real call. */
  const playClip = async () => {
    const s = clip.current
    if (!s || !audio.current) return
    clip.current = null
    const blob = await (await fetch(`/api/try/samples/${encodeURIComponent(s.id)}`)).blob()
    await audio.current?.setSource({ kind: 'file', file: new File([blob], `${s.id}.wav`) })
  }

  /** Agent lines are spoken one after another. On a mic call the mic is muted meanwhile, so the bank never scores its own voice. */
  const agentSays = (text: string, challenge?: string) => {
    setView((v) => (v ? { ...v, lines: [...v.lines, { who: 'bank' as const, text }].slice(-4), challenge: challenge ?? v.challenge } : v))
    queue.current = queue.current.then(async () => {
      const mic = !clip.current && !playing.current
      if (mic) audio.current?.mute(true)
      await speak(text)
      await new Promise((r) => window.setTimeout(r, 250)) // let the speaker's echo die away
      if (mic) audio.current?.mute(false)
      if (challenge && ws.current?.readyState === 1) ws.current.send(JSON.stringify({ type: 'read_done' }))
      if (clip.current) {
        playing.current = true
        await playClip()
      }
    })
  }

  const hangup = async () => {
    try {
      ws.current?.send(JSON.stringify({ type: 'hangup' }))
    } catch {
      /* already closed */
    }
    ws.current?.close()
    ws.current = null
    window.speechSynthesis?.cancel()
    await audio.current?.stop()
    audio.current = null
    setView((v) => (v ? { ...v, state: 'ended', challenge: null } : v))
    if (cid) refresh(cid).catch(() => {})
  }

  const dial = async (sample?: Sample) => {
    if (!cid) return
    if ('speechSynthesis' in window) window.speechSynthesis.speak(new SpeechSynthesisUtterance('')) // iPhones only speak after a tap
    const a = new PhoneAudio()
    try {
      await a.start(sample ? { kind: 'none' } : { kind: 'mic' })
    } catch (e) {
      show('Could not open the microphone: ' + (e as Error).message, 'error')
      return
    }
    audio.current = a
    queue.current = Promise.resolve()
    clip.current = sample ?? null
    playing.current = false
    setView({ state: 'connecting', started: Date.now(), voice: sample ? sample.label : 'your own voice', lines: [], challenge: null, call: null, result: null })
    const sock = new WebSocket(wsUrl(`/ws/caller?sandbox=${encodeURIComponent(cid)}&lang=en`))
    sock.binaryType = 'arraybuffer'
    a.onFrame = (b) => sock.readyState === 1 && sock.send(b)
    sock.onmessage = async (m) => {
      if (m.data instanceof ArrayBuffer) return
      const e = JSON.parse(m.data)
      if (e.type === 'ping') sock.send(JSON.stringify({ type: 'pong', t: e.t }))
      else if (e.type === 'busy' || e.type === 'error') {
        show(e.message, 'error')
        hangup()
      } else if (e.type === 'answered') {
        setView((v) => (v ? { ...v, state: 'live', started: Date.now() } : v))
      } else if (e.type === 'agent') agentSays(e.say, e.challenge)
      else if (e.type === 'verdict' && e.event.type === 'state') setView((v) => (v ? { ...v, call: e.event.call as Call } : v))
      else if (e.type === 'result') setView((v) => (v ? { ...v, result: { outcome: e.outcome, tier: e.tier }, challenge: null } : v))
      else if (e.type === 'ended') queue.current.then(hangup)
    }
    sock.onclose = () => setView((v) => (v && v.state !== 'ended' ? { ...v, state: 'ended' } : v))
    ws.current = sock
  }

  const bind = async () => {
    if (!cid) return
    try {
      const optionsJSON = await api.post<Parameters<typeof startRegistration>[0]['optionsJSON']>(`/api/app/${cid}/passkey/options`)
      const credential = await startRegistration({ optionsJSON })
      await api.post(`/api/app/${cid}/passkey/verify`, { credential, device: deviceLabel() })
      show('This phone is bound to your account')
      refresh(cid)
    } catch (e) {
      show((e as Error).message, 'error')
    }
  }

  const decide = async (decision: 'approve' | 'decline') => {
    if (!approval) return
    setBusy(true)
    try {
      let credential = undefined
      if (decision === 'approve') {
        const optionsJSON = await api.post<Parameters<typeof startAuthentication>[0]['optionsJSON']>(`/api/approvals/${approval.id}/options`)
        credential = await startAuthentication({ optionsJSON })
      }
      await api.post(`/api/approvals/${approval.id}/decide`, { decision, credential })
      setApproval(null)
      show(decision === 'approve' ? 'Approved and signed with your passkey' : "Thanks. We've stopped it.")
    } catch (e) {
      show((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!home) return <div className="grid h-full place-items-center text-muted">Setting up your demo account…{toast}</div>
  const c = home.customer
  const bound = home.passkeys.length > 0
  const android = /Android/i.test(navigator.userAgent)

  return (
    <div className="min-h-full">
      <TopBar title="Try Countersign" right={<span className="text-muted">{c.name}</span>} />
      <main className="mx-auto max-w-md space-y-4 p-4">
        <section>
          <h1 className="text-2xl font-bold">You're a customer of Countersign Bank</h1>
          <p className="mt-1 text-sm text-muted">
            Call the bank and ask to change your registered mobile number: first as yourself, then with a cloned voice. Watch what the bank sees, and answer the approval on this
            phone. A virtual agent answers; everything else is the real system.
          </p>
          <div className="card mt-3 grid grid-cols-2 gap-2 p-3 text-sm">
            <div><div className="text-xs text-muted">Registered mobile</div><div className="font-mono">{c.registered_mobile}</div></div>
            <div><div className="text-xs text-muted">Balance</div><div>{inr(c.balance)}</div></div>
          </div>
        </section>

        <Step n={1} title="Bind this phone" done={bound}>
          <p className="text-sm text-muted">Creates a passkey, so this phone can approve changes with your fingerprint or screen lock. Skip it and the phone can only say no.</p>
          {!bound && (
            <button className="btn-primary mt-2 w-full py-3" disabled={!browserSupportsWebAuthn()} onClick={bind}>
              Bind this phone
            </button>
          )}
        </Step>

        <Step n={2} title="Call the bank as yourself">
          <p className="text-sm text-muted">Speak normally. Tell the agent why you need a new number.</p>
          <button className="btn-primary mt-2 w-full py-3" disabled={!!view && view.state !== 'ended'} onClick={() => dial()}>
            Call the bank
          </button>
        </Step>

        <Step n={3} title="Call with a cloned voice">
          {samples.length === 0 ? (
            <p className="text-sm text-muted">No cloned-voice samples are loaded on this server yet. Ask the team to play one for you.</p>
          ) : (
            <>
              <p className="text-sm text-muted">The phone plays a voice clone (made with consent) into the call instead of your mic. The attacker even calls from your number.</p>
              <div className="mt-2 space-y-2">
                {samples.map((s) => (
                  <button key={s.id} className="btn-outline w-full py-3" disabled={!!view && view.state !== 'ended'} onClick={() => dial(s)}>
                    {s.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </Step>

        <Step n={4} title="Pay someone new after a call">
          <p className="text-sm text-muted">Right after a call, send money by UPI to a new payee. The bank app pauses it and says why.</p>
          <Link to={`/bank/${c.id}`} className="btn-outline mt-2 block w-full py-3 text-center no-underline">
            Open your bank app
          </Link>
        </Step>

        {android && (
          <section className="card space-y-2 p-4">
            <div className="font-semibold">On Android: real call alerts</div>
            {inAndroidApp() ? (
              <CallAlerts customer={c.id} toast={show} />
            ) : apk ? (
              <>
                <p className="text-sm text-muted">The CS Bank app tells the bank when you're on a real call (normal or WhatsApp) and shows approvals as notifications. It sets itself up.</p>
                <a href="/download/cs-bank.apk" className="btn-outline block w-full py-3 text-center no-underline">Download the CS Bank app</a>
              </>
            ) : (
              <p className="text-sm text-muted">The CS Bank app isn't on this server yet.</p>
            )}
          </section>
        )}

        <p className="pb-6 text-center text-sm">
          <Link to="/metrics">How well does it work? Our numbers, misses included →</Link>
        </p>
      </main>

      {view && <CallScreen view={view} onHangup={hangup} onClose={() => setView(null)} />}
      {approval && <ApprovalSheet a={approval} busy={busy} onDecide={decide} hasPasskey={bound} />}
      {toast}
    </div>
  )
}

function Step({ n, title, done, children }: { n: number; title: string; done?: boolean; children: React.ReactNode }) {
  return (
    <section className="card p-4">
      <div className="flex items-center gap-2">
        <span className={`grid h-6 w-6 place-items-center rounded-full text-xs font-bold ${done ? 'bg-green text-white' : 'bg-brand text-white'}`}>{done ? '✓' : n}</span>
        <h2 className="font-semibold">{title}</h2>
      </div>
      <div className="mt-1">{children}</div>
    </section>
  )
}

function CallScreen({ view, onHangup, onClose }: { view: CallView; onHangup: () => void; onClose: () => void }) {
  const call = view.call
  const v = call?.verdict
  const outcome = view.result ? OUTCOME[view.result.outcome] : null
  return (
    <div className="fixed inset-0 z-30 overflow-y-auto bg-paper">
      <div className="mx-auto max-w-md space-y-3 p-4">
        <div className="flex items-center justify-between text-sm">
          <span className="font-semibold">Countersign Bank</span>
          <span className="text-muted">
            {view.state === 'connecting' ? 'calling…' : view.state === 'live' ? clock((Date.now() - view.started) / 1000) : 'call ended'} · {view.voice}
          </span>
        </div>

        <section className="card space-y-2 p-3">
          <div className="label">The bank's agent</div>
          {view.lines.length === 0 && <p className="text-sm text-muted">Ringing…</p>}
          {view.lines.map((l, i) => (
            <p key={i} className={`text-sm ${i === view.lines.length - 1 ? 'text-ink' : 'text-muted'}`}>{l.text}</p>
          ))}
          {view.challenge && (
            <div className="rounded-lg bg-brand p-3 text-center text-white">
              <div className="text-xs uppercase tracking-wide opacity-80">Say this now</div>
              <div className="mt-1 text-xl font-bold">{view.challenge.replace(/^Please (say|whisper|repeat these numbers quickly):\s*/i, '').replace(/"/g, '')}</div>
            </div>
          )}
        </section>

        <section className="card space-y-2 p-3">
          <div className="flex items-center justify-between">
            <div className="label">What the bank sees</div>
            <TierPill tier={call?.tier ?? null} />
          </div>
          {!call?.tier && <p className="text-sm text-muted">Listening. The first verdict comes after a few seconds of speech.</p>}
          {v?.reason_text && v.reason_text.length > 0 && (
            <ul className="list-disc pl-5 text-sm">
              {v.reason_text.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
          {call && call.windows.length > 0 && (
            <>
              <Spark values={call.windows.map((w) => w.p)} height={48} />
              <p className="text-xs text-muted">Chance each 4-second window is a machine voice. AMBER from 0.3, RED from 0.7.</p>
            </>
          )}
          {call?.requests.map((r) => (
            <div key={r.id} className="rounded-md bg-line/50 p-2 text-xs">
              <div className="font-semibold">Request: change registered mobile · {r.policy.tier}</div>
              <div>{r.policy.note}</div>
              {r.missing.length > 0 && <div className="text-muted">Still needed: {r.missing.join(', ').replace(/_/g, ' ')}</div>}
            </div>
          ))}
        </section>

        {outcome && <div className={`rounded-lg p-3 text-center font-semibold ${outcome.tone}`}>{outcome.title}</div>}

        {view.state === 'ended' ? (
          <button className="btn-primary w-full py-3" onClick={onClose}>Back</button>
        ) : (
          <button className="btn-danger w-full py-3" onClick={onHangup}>End call</button>
        )}
      </div>
    </div>
  )
}
