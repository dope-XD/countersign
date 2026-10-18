import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { browserSupportsWebAuthn, startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { api } from '../lib/api'
import { useEvents } from '../lib/events'
import { inr, type Approval, type Customer } from '../lib/types'
import { Dot, Signature, useToast } from '../components/ui'

type Home = {
  customer: Customer
  passkeys: { id: string; device_label: string; created_at: number }[]
  pending: Approval[]
  payments: { id: string; details: { payee: string; amount: number }; status: string; created_at: number }[]
  family: Customer[]
}
type PayResult = {
  payment_id: string
  status: string
  amount_text: string
  guard: { fires: boolean; reasons: string[]; call_seen: boolean; new_payee: boolean }
  family: { id: string; name: string; mobile: string }[]
}
type VoiceResult = { verdict: string; message: string; seconds: number; s1?: number; model?: string }
type Report = { id: string; helpline: string; portal: string; category: string; amount_attempted: number; payee_vpa: string; description: string }
type Alert = { title: string; body: string }

type Screen = 'home' | 'pay' | 'paused' | 'waiting' | 'done' | 'voice' | 'security'

function deviceLabel() {
  const ua = navigator.userAgent
  const m = ua.match(/Android [\d.]+; ([^)]+)\)/) || ua.match(/(iPhone|iPad|Macintosh|Windows NT [\d.]+)/)
  return m ? m[1].trim() : 'this device'
}

export default function Bank() {
  const { customer = 'rahul' } = useParams()
  const [home, setHome] = useState<Home | null>(null)
  const [screen, setScreen] = useState<Screen>('home')
  const [approval, setApproval] = useState<Approval | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [pay, setPay] = useState<PayResult | null>(null)
  const [outcome, setOutcome] = useState<{ status: string; message: string; report?: Report } | null>(null)
  const [busy, setBusy] = useState(false)
  const { show, node: toast } = useToast()

  const load = useCallback(async () => {
    try {
      const h = await api.get<Home>(`/api/app/${customer}/home`)
      setHome(h)
      setApproval((cur) => cur ?? h.pending[0] ?? null)
    } catch (e) {
      show((e as Error).message, 'error')
    }
  }, [customer, show])

  useEffect(() => {
    load()
  }, [load])

  const connected = useEvents([`app:${customer}`], (e) => {
    if (e.type === 'approval') {
      setApproval(e.approval as Approval)
      if (navigator.vibrate) navigator.vibrate([200, 100, 200])
    }
    if (e.type === 'alert') setAlerts((a) => [{ title: String(e.title), body: String(e.body) }, ...a].slice(0, 3))
    if (e.type === 'payment') {
      setOutcome({ status: String(e.status), message: String(e.message), report: e.report as Report | undefined })
      setScreen('done')
      load()
    }
  })

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
      show(decision === 'approve' ? 'Approved and signed with your passkey' : "Thanks. We've stopped it.")
      setApproval(null)
      load()
    } catch (e) {
      show((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!home) return <div className="grid h-full place-items-center text-muted">Loading…</div>
  const c = home.customer
  const first = c.name.split(' ')[0]

  return (
    <div className="mx-auto min-h-full max-w-md bg-paper pb-10">
      <header className="flex items-center justify-between px-4 pb-2 pt-4">
        <div className="flex items-center gap-2">
          <Signature className="h-4 w-10 text-brand" />
          <span className="font-display font-bold">Countersign Bank</span>
        </div>
        <span className="flex items-center gap-2 text-xs text-muted">
          {first} <Dot ok={connected} />
        </span>
      </header>

      {alerts.map((a, i) => (
        <div key={i} className="mx-4 mt-2 rounded-lg border border-amber/30 bg-amber-soft p-3 text-sm">
          <div className="font-semibold">{a.title}</div>
          <div className="text-ink/80">{a.body}</div>
          <button className="mt-1 text-xs text-muted underline" onClick={() => setAlerts(alerts.filter((_, j) => j !== i))}>Dismiss</button>
        </div>
      ))}

      {home.passkeys.length === 0 && screen === 'home' && (
        <button className="mx-4 mt-3 block w-[calc(100%-2rem)] rounded-lg border border-brand bg-brand-soft p-3 text-left text-sm" onClick={() => setScreen('security')}>
          <div className="font-semibold text-brand">Bind this phone to your account</div>
          <div className="text-ink/80">Risky changes will need your fingerprint or screen lock on this phone. A voice alone can't approve them.</div>
        </button>
      )}

      <main className="px-4">
        {screen === 'home' && (
          <>
            <section className="mt-4 rounded-xl bg-brand p-5 text-white">
              <div className="text-xs opacity-80">Savings ••••{c.account_no.slice(-4)}</div>
              <div className="mt-1 font-display text-3xl font-bold">{inr(c.balance)}</div>
              <div className="mt-2 text-xs opacity-80">{c.upi_id}</div>
            </section>
            <section className="mt-4 grid grid-cols-2 gap-3">
              <Tile title="Pay by UPI" sub="Send money" onClick={() => setScreen('pay')} />
              <Tile title="Check a voice note" sub="Is this voice real?" onClick={() => setScreen('voice')} />
              <Tile title="Security" sub={`${home.passkeys.length} passkey${home.passkeys.length === 1 ? '' : 's'}`} onClick={() => setScreen('security')} />
              <Tile title="Family Circle" sub={home.family.map((f) => f.name.split(' ')[0]).join(', ') || 'Not set'} onClick={() => show(`${home.family.map((f) => f.name).join(', ')} can confirm payments with you.`)} />
            </section>
            <section className="mt-6">
              <div className="label">Recent</div>
              <ul className="mt-2 divide-y divide-line rounded-lg border border-line bg-card">
                {home.payments.length === 0 && <li className="p-3 text-sm text-muted">No payments yet.</li>}
                {home.payments.map((p) => (
                  <li key={p.id} className="flex items-center justify-between p-3 text-sm">
                    <span className="truncate">{p.details.payee}</span>
                    <span className="text-right">
                      <span className="font-semibold">{inr(p.details.amount)}</span>
                      <span className={`block text-xs ${p.status === 'executed' ? 'text-green' : p.status === 'cancelled' ? 'text-red' : 'text-amber'}`}>{p.status.replace('_', ' ')}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}

        {screen === 'pay' && (
          <PayForm
            customer={c}
            onBack={() => setScreen('home')}
            onResult={(r) => {
              setPay(r)
              if (r.status === 'paused') setScreen('paused')
              else {
                setOutcome({ status: 'executed', message: `${r.amount_text} sent.` })
                setScreen('done')
                load()
              }
            }}
          />
        )}

        {screen === 'paused' && pay && (
          <PauseScreen
            pay={pay}
            onAsk={async (fid) => {
              try {
                await api.post(`/api/payments/${pay.payment_id}/ask-family`, { family_id: fid })
                setScreen('waiting')
              } catch (e) {
                show((e as Error).message, 'error')
              }
            }}
            onVoice={() => setScreen('voice')}
            onContinue={async () => {
              await api.post(`/api/payments/${pay.payment_id}/continue`)
              setOutcome({ status: 'executed', message: `${pay.amount_text} sent.` })
              setScreen('done')
              load()
            }}
            onCancel={async () => {
              await api.post(`/api/payments/${pay.payment_id}/cancel`)
              setScreen('home')
              load()
            }}
          />
        )}

        {screen === 'waiting' && pay && (
          <section className="mt-10 text-center">
            <div className="mx-auto h-12 w-12 animate-spin rounded-full border-4 border-brand-soft border-t-brand" />
            <h2 className="mt-6 text-xl font-bold">Asking {pay.family[0]?.name} on their phone…</h2>
            <p className="mt-2 text-sm text-muted">Your {pay.amount_text} payment is on hold until they answer. Nothing has been sent.</p>
            <button className="btn-ghost mt-6 text-sm underline" onClick={() => setScreen('paused')}>Back</button>
          </section>
        )}

        {screen === 'done' && outcome && (
          <section className="mt-8">
            <div className={`rounded-xl p-5 ${outcome.status === 'cancelled' ? 'bg-red-soft' : 'bg-green-soft'}`}>
              <h2 className="text-xl font-bold">{outcome.status === 'cancelled' ? 'Payment cancelled' : 'Done'}</h2>
              <p className="mt-1 text-sm">{outcome.message}</p>
            </div>
            {outcome.report && (
              <div className="mt-4 rounded-lg border border-line bg-card p-4 text-sm">
                <div className="label">Report to the cyber-fraud helpline</div>
                <p className="mt-2">We've filled in a report for you. Call <b>1930</b> now, or submit it on {outcome.report.portal}. Reporting quickly gives the best chance of a fund hold.</p>
                <dl className="mt-3 space-y-1 text-xs">
                  <div><dt className="inline text-muted">Category: </dt><dd className="inline">{outcome.report.category}</dd></div>
                  <div><dt className="inline text-muted">Amount: </dt><dd className="inline">{inr(outcome.report.amount_attempted)}</dd></div>
                  <div><dt className="inline text-muted">Payee: </dt><dd className="inline font-mono">{outcome.report.payee_vpa}</dd></div>
                </dl>
                <a className="btn-primary mt-3 w-full" href="tel:1930">Call 1930</a>
              </div>
            )}
            <button className="btn-outline mt-4 w-full" onClick={() => setScreen('home')}>Back to home</button>
          </section>
        )}

        {screen === 'voice' && <VoiceNote onBack={() => setScreen(pay && pay.status === 'paused' ? 'paused' : 'home')} />}

        {screen === 'security' && <Security customer={customer} home={home} reload={load} onBack={() => setScreen('home')} toast={show} />}
      </main>

      {approval && <ApprovalSheet a={approval} busy={busy} onDecide={decide} hasPasskey={home.passkeys.length > 0} />}
      {toast}
    </div>
  )
}

function Tile({ title, sub, onClick }: { title: string; sub: string; onClick: () => void }) {
  return (
    <button className="rounded-lg border border-line bg-card p-4 text-left" onClick={onClick}>
      <div className="font-semibold">{title}</div>
      <div className="text-xs text-muted">{sub}</div>
    </button>
  )
}

function PayForm({ customer, onBack, onResult }: { customer: Customer; onBack: () => void; onResult: (r: PayResult) => void }) {
  const [payee, setPayee] = useState('')
  const [amount, setAmount] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const submit = async () => {
    setErr(null)
    try {
      onResult(await api.post<PayResult>(`/api/app/${customer.id}/pay`, { payee, amount: Number(amount) }))
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  return (
    <section className="mt-4 space-y-3">
      <button className="text-sm text-muted" onClick={onBack}>← Back</button>
      <h2 className="text-xl font-bold">Pay by UPI</h2>
      <label className="block">
        <span className="label">To UPI ID</span>
        <input className="input mt-1" value={payee} onChange={(e) => setPayee(e.target.value)} placeholder="name@bank" list="payees" autoCapitalize="none" />
        <datalist id="payees">
          {customer.known_payees.map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
      </label>
      <label className="block">
        <span className="label">Amount (₹)</span>
        <input className="input mt-1 text-lg" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d]/g, ''))} />
      </label>
      {err && <p className="text-sm text-red">{err}</p>}
      <button className="btn-primary w-full py-3" disabled={!payee || !amount} onClick={submit}>Pay</button>
    </section>
  )
}

function PauseScreen({ pay, onAsk, onVoice, onContinue, onCancel }: {
  pay: PayResult
  onAsk: (familyId: string) => void
  onVoice: () => void
  onContinue: () => void
  onCancel: () => void
}) {
  const fam = pay.family[0]
  const g = pay.guard
  const r = g.reasons
  const list = r.length > 1 ? `${r.slice(0, -1).join(', ')} and ${r[r.length - 1]}` : r[0] || ''
  const why = list ? list.replace(/^./, (m) => m.toUpperCase()) + '.' : ''
  return (
    <section className="mt-6">
      <h2 className="font-display text-2xl font-extrabold leading-tight">We’ve paused this {pay.amount_text} payment for a moment</h2>
      <p className="mt-3 text-sm text-ink/80">
        {why} Calls asking for urgent money are a common scam, even when the voice sounds like family.
      </p>
      <div className="mt-6 space-y-3">
        {fam && (
          <button className="btn-primary w-full py-3" onClick={() => onAsk(fam.id)}>Ask {fam.name} on {fam.name === 'Rahul' ? 'his' : 'their'} phone</button>
        )}
        {fam && (
          <a className="btn-outline w-full py-3" href={`tel:${fam.mobile}`}>Call {fam.name}'s saved number</a>
        )}
        <button className="btn-outline w-full py-3" onClick={onVoice}>Check a voice note</button>
        <div className="flex justify-between pt-2 text-sm">
          <button className="text-muted underline" onClick={onCancel}>Cancel payment</button>
          <button className="text-muted underline" onClick={onContinue}>Continue with payment</button>
        </div>
      </div>
    </section>
  )
}

function VoiceNote({ onBack }: { onBack: () => void }) {
  const [res, setRes] = useState<VoiceResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const upload = async (f: File) => {
    setBusy(true)
    setErr(null)
    setRes(null)
    try {
      setRes(await api.upload<VoiceResult>('/api/voice-note', f))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const tone = res?.verdict === 'likely_synthetic' ? 'bg-red-soft' : res?.verdict === 'unsure' ? 'bg-amber-soft' : 'bg-green-soft'
  return (
    <section className="mt-4 space-y-3">
      <button className="text-sm text-muted" onClick={onBack}>← Back</button>
      <h2 className="text-xl font-bold">Check a voice note</h2>
      <p className="text-sm text-muted">Share a WhatsApp voice message or pick an audio file. We check it on our servers in India and delete it straight away.</p>
      <label className="btn-outline w-full cursor-pointer py-3">
        {busy ? 'Checking…' : 'Choose a voice note'}
        <input type="file" accept="audio/*,.opus,.ogg,.m4a,.aac" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </label>
      {err && <p className="text-sm text-red">{err}</p>}
      {res && (
        <div className={`rounded-lg p-4 text-sm ${tone}`}>
          <p className="font-semibold">{res.message}</p>
          <p className="mt-2 text-xs text-muted">{res.seconds} s checked · not stored</p>
        </div>
      )}
    </section>
  )
}

function Security({ customer, home, reload, onBack, toast }: { customer: string; home: Home; reload: () => void; onBack: () => void; toast: (m: string, t?: 'info' | 'error') => void }) {
  const supported = browserSupportsWebAuthn()
  const enrol = async () => {
    try {
      const optionsJSON = await api.post<Parameters<typeof startRegistration>[0]['optionsJSON']>(`/api/app/${customer}/passkey/options`)
      const credential = await startRegistration({ optionsJSON })
      await api.post(`/api/app/${customer}/passkey/verify`, { credential, device: deviceLabel() })
      toast('This phone is now bound to your account')
      reload()
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }
  return (
    <section className="mt-4 space-y-3">
      <button className="text-sm text-muted" onClick={onBack}>← Back</button>
      <h2 className="text-xl font-bold">Security</h2>
      <p className="text-sm text-muted">Changes to your mobile number, new payees and higher limits need approval on a bound phone, signed with your fingerprint or screen lock. Losing your phone? Visit a branch or use video-KYC.</p>
      {!supported && <p className="rounded-md bg-red-soft p-3 text-sm text-red">This browser doesn't support passkeys. Open this page in Chrome or Safari over HTTPS.</p>}
      <ul className="divide-y divide-line rounded-lg border border-line bg-card">
        {home.passkeys.length === 0 && <li className="p-3 text-sm text-muted">No phone bound yet.</li>}
        {home.passkeys.map((p) => (
          <li key={p.id} className="p-3 text-sm">
            <div className="font-semibold">{p.device_label}</div>
            <div className="text-xs text-muted">bound {new Date(p.created_at * 1000).toLocaleString()}</div>
          </li>
        ))}
      </ul>
      <button className="btn-primary w-full py-3" disabled={!supported} onClick={enrol}>Bind this phone (create passkey)</button>
      {home.passkeys.length > 0 && (
        <button className="btn-ghost w-full text-xs" onClick={async () => { await api.del(`/api/app/${customer}/passkeys`); reload() }}>Remove all bound phones (demo reset)</button>
      )}
    </section>
  )
}

function ApprovalSheet({ a, busy, onDecide, hasPasskey }: { a: Approval; busy: boolean; onDecide: (d: 'approve' | 'decline') => void; hasPasskey: boolean }) {
  const family = a.kind === 'family_ping'
  return (
    <div className="fixed inset-0 z-40 flex items-end bg-ink/40 sm:items-center sm:justify-center">
      <div className="w-full max-w-md rounded-t-2xl bg-white p-5 shadow-2xl sm:rounded-2xl">
        <div className="label">{family ? 'Family Circle' : 'Approval needed'}</div>
        <h2 className="mt-2 font-display text-2xl font-bold leading-tight">{a.summary.question}</h2>
        {a.summary.detail && <p className="mt-2 text-sm text-ink/80">{a.summary.detail}</p>}
        {!family && <p className="mt-2 text-xs text-muted">Requested on a {String(a.summary.channel || 'call')} just now. If you are not on the phone with us right now, tap No.</p>}
        <div className="mt-5 space-y-2">
          <button className="btn-danger w-full py-3 text-base" disabled={busy} onClick={() => onDecide('decline')}>
            {family ? "No, I didn't ask" : "No, this wasn't me"}
          </button>
          <button className="btn-outline w-full py-3" disabled={busy || !hasPasskey} onClick={() => onDecide('approve')}>
            {family ? 'Yes, I asked · confirm with passkey' : 'Yes, approve with passkey'}
          </button>
          {!hasPasskey && <p className="text-center text-xs text-muted">No passkey on this phone, so it can only decline.</p>}
        </div>
      </div>
    </div>
  )
}
