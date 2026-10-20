import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { TopBar } from '../components/ui'
import { useToast } from '../lib/useToast'

type Item = { id: string; kind: 'opening' | 'challenge' | 'passage' | 'voice_note'; lang: string; text: string }

const KIND: Record<Item['kind'], string> = {
  opening: 'Call opening: ask the bank for a risky change',
  challenge: 'Liveness challenge reply: say it as you would to an agent',
  passage: 'Read or talk naturally',
  voice_note: 'WhatsApp-style voice note',
}

/** IndiaCall recorder: consented teammates record the fixed script used for evaluation. */
export default function Record() {
  const [speaker, setSpeaker] = useState(() => localStorage.getItem('ic.speaker') || '')
  const [consented, setConsented] = useState(() => localStorage.getItem('ic.consented') === '1')
  const [name, setName] = useState('')
  const [agree, setAgree] = useState(false)
  const [clone, setClone] = useState(false)
  const [ageBand, setAgeBand] = useState('')
  const [gender, setGender] = useState('')
  const [items, setItems] = useState<Item[]>([])
  const [done, setDone] = useState<string[]>([])
  const [rec, setRec] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const mr = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const { show, node: toast } = useToast()

  useEffect(() => {
    api.get<Item[]>('/api/indiacall/items').then(setItems)
  }, [])
  useEffect(() => {
    if (consented && speaker) api.get<{ done: string[] }>(`/api/indiacall/progress/${speaker}`).then((d) => setDone(d.done))
  }, [consented, speaker])

  const giveConsent = async () => {
    try {
      await api.post('/api/indiacall/consent', {
        speaker,
        name,
        agree,
        clone,
        age_band: ageBand || null,
        gender: gender || null,
        languages: ['hi', 'en', 'hinglish'],
      })
      localStorage.setItem('ic.speaker', speaker)
      localStorage.setItem('ic.consented', '1')
      setConsented(true)
    } catch (e) {
      show((e as Error).message, 'error')
    }
  }

  // the next volunteer on the same laptop must not record under the previous speaker id
  const switchSpeaker = () => {
    localStorage.removeItem('ic.speaker')
    localStorage.removeItem('ic.consented')
    setSpeaker('')
    setName('')
    setAgree(false)
    setClone(false)
    setAgeBand('')
    setGender('')
    setDone([])
    setConsented(false)
  }

  const start = async (id: string) => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: true } })
    const type = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg'].find((t) => MediaRecorder.isTypeSupported(t)) || ''
    const m = new MediaRecorder(stream, type ? { mimeType: type } : undefined)
    chunks.current = []
    m.ondataavailable = (e) => e.data.size && chunks.current.push(e.data)
    m.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop())
      const blob = new Blob(chunks.current, { type: m.mimeType })
      const ext = m.mimeType.includes('mp4') ? 'm4a' : m.mimeType.includes('ogg') ? 'ogg' : 'webm'
      const fd = new FormData()
      fd.append('speaker', speaker)
      fd.append('item', id)
      fd.append('file', blob, `${id}.${ext}`)
      setBusy(id)
      try {
        const res = await fetch('/api/indiacall/upload', { method: 'POST', body: fd })
        if (!res.ok) throw new Error((await res.json()).detail || res.statusText)
        setDone((d) => [...new Set([...d, id])])
      } catch (e) {
        show((e as Error).message, 'error')
      } finally {
        setBusy(null)
      }
    }
    m.start()
    mr.current = m
    setRec(id)
  }

  const stop = () => {
    mr.current?.stop()
    mr.current = null
    setRec(null)
  }

  if (!consented) {
    return (
      <div className="min-h-full">
        <TopBar title="IndiaCall recorder" />
        <main className="mx-auto max-w-xl space-y-4 p-4">
          <h1 className="text-2xl font-bold">Before you record</h1>
          <div className="card space-y-2 p-4 text-sm">
            <p>Your recordings are used only to test Countersign at RAKSHAM 2026.</p>
            <p>Volunteers record their real voice only. Teammates may also agree to <b>cloned versions of their voice</b> being made to attack our own system. Every cloned file is labelled synthetic, is never shared or published, and is deleted after the event, together with the recordings.</p>
            <p>Your voice is never used to train the detector, so the test stays fair. You can withdraw at any time and we delete everything.</p>
            <p>Please also sign the paper consent form (docs/CONSENT.md).</p>
          </div>
          <input className="input" placeholder="Short speaker id, e.g. pushkar" value={speaker} onChange={(e) => setSpeaker(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ''))} />
          <input className="input" placeholder="Full name" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="grid grid-cols-2 gap-2">
            <select className="input" value={ageBand} onChange={(e) => setAgeBand(e.target.value)} aria-label="Age band (optional)">
              <option value="">Age band (optional)</option>
              {['18-29', '30-44', '45-59', '60+'].map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <select className="input" value={gender} onChange={(e) => setGender(e.target.value)} aria-label="Gender (optional)">
              <option value="">Gender (optional)</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="other">Other</option>
            </select>
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-1" />
            I agree to be recorded for this test only, on the terms above.
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={clone} onChange={(e) => setClone(e.target.checked)} className="mt-1" />
            I also agree to cloned versions of my voice being made for the attack tests (teammates only; leave this unticked if you are a volunteer).
          </label>
          <button className="btn-primary w-full" disabled={!agree || !speaker || !name} onClick={giveConsent}>Continue</button>
        </main>
        {toast}
      </div>
    )
  }

  return (
    <div className="min-h-full">
      <TopBar
        title="IndiaCall recorder"
        right={
          <span className="text-muted">
            {speaker} · {done.length}/{items.length} ·{' '}
            <button className="underline" onClick={switchSpeaker}>Switch speaker</button>
          </span>
        }
      />
      <main className="mx-auto max-w-2xl space-y-3 p-4">
        <p className="text-sm text-muted">Quiet room, phone or laptop mic, normal speaking distance. Record each line once; re-record anytime. Speak as you would on a real call.</p>
        {items.map((it) => (
          <div key={it.id} className={`card p-4 ${done.includes(it.id) ? 'border-green/40' : ''}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="label">{it.id} · {KIND[it.kind]}</span>
              {done.includes(it.id) && <span className="text-xs font-semibold text-green">recorded</span>}
            </div>
            <p className="mt-2 text-lg">{it.text}</p>
            <div className="mt-3">
              {rec === it.id ? (
                <button className="btn-danger" onClick={stop}>Stop and save</button>
              ) : (
                <button className="btn-outline" disabled={!!rec || busy === it.id} onClick={() => start(it.id)}>
                  {busy === it.id ? 'Saving…' : done.includes(it.id) ? 'Re-record' : 'Record'}
                </button>
              )}
            </div>
          </div>
        ))}
      </main>
      {toast}
    </div>
  )
}
