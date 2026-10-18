import { useEffect, useRef, useState } from 'react'
import { wsUrl } from '../lib/api'
import { PhoneAudio, listMics } from '../lib/phoneAudio'
import { clock } from '../lib/types'
import { Signature } from '../components/ui'

const PRESETS = [
  { label: "Rahul's registered number", cli: '+919845012210' },
  { label: "Sunita's registered number", cli: '+919415033618' },
  { label: 'Unknown number', cli: '+917000012345' },
  { label: 'Number flagged on DoT FRI', cli: '+918877665544' },
]

type State = 'idle' | 'ringing' | 'live' | 'ended'

/** A softphone for any phone browser. Audio leaves the device as 8 kHz mu-law, like a PSTN call. */
export default function Caller() {
  const [cli, setCli] = useState(PRESETS[0].cli)
  const [lang, setLang] = useState('hinglish')
  const [mode, setMode] = useState<'mic' | 'file'>('mic')
  const [file, setFile] = useState<File | null>(null)
  const [mics, setMics] = useState<MediaDeviceInfo[]>([])
  const [mic, setMic] = useState('')
  const [state, setState] = useState<State>('idle')
  const [muted, setMuted] = useState(false)
  const [level, setLevel] = useState(0)
  const [since, setSince] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const [, tick] = useState(0)
  const ws = useRef<WebSocket | null>(null)
  const audio = useRef<PhoneAudio | null>(null)

  useEffect(() => {
    listMics().then(setMics)
    const id = window.setInterval(() => tick((x) => x + 1), 1000)
    return () => window.clearInterval(id)
  }, [])

  const hangup = async () => {
    try {
      ws.current?.send(JSON.stringify({ type: 'hangup' }))
    } catch {
      /* closed */
    }
    ws.current?.close()
    await audio.current?.stop()
    audio.current = null
    setState('ended')
  }

  const dial = async () => {
    setErr(null)
    if (mode === 'file' && !file) {
      setErr('Choose an audio file to play into the call.')
      return
    }
    const a = new PhoneAudio()
    try {
      // file playback starts only once the agent answers
      await a.start(mode === 'mic' ? { kind: 'mic', deviceId: mic || undefined } : { kind: 'none' })
    } catch (e) {
      setErr('Could not open the microphone: ' + (e as Error).message)
      return
    }
    audio.current = a
    a.onLevel = setLevel
    const sock = new WebSocket(wsUrl(`/ws/caller?cli=${encodeURIComponent(cli)}&lang=${lang}`))
    sock.binaryType = 'arraybuffer'
    a.onFrame = (b) => {
      if (sock.readyState === 1) sock.send(b)
    }
    sock.onmessage = async (m) => {
      if (m.data instanceof ArrayBuffer) {
        a.play(m.data)
        return
      }
      const e = JSON.parse(m.data)
      if (e.type === 'ping') sock.send(JSON.stringify({ type: 'pong', t: e.t }))
      if (e.type === 'answered') {
        setState('live')
        setSince(Date.now())
        if (mode === 'file' && file) await a.setSource({ kind: 'file', file })
      }
      if (e.type === 'ended') hangup()
    }
    sock.onerror = () => setErr('Could not reach the bank. Check the connection and try again.')
    sock.onclose = () => {
      setState((s) => (s === 'idle' ? s : 'ended'))
      void a.stop()
    }
    ws.current = sock
    setState('ringing')
  }

  useEffect(() => () => void audio.current?.stop(), [])

  const toggleMute = () => {
    audio.current?.mute(!muted)
    setMuted(!muted)
  }

  return (
    <div className="mx-auto flex min-h-full max-w-md flex-col px-4 py-6">
      <div className="flex items-center gap-2">
        <Signature className="h-5 w-12 text-brand" />
        <span className="font-display text-lg font-bold">Call the bank</span>
      </div>
      <p className="mt-1 text-sm text-muted">Countersign Bank customer care · 1800 000 0000 (demo line)</p>

      {state === 'idle' || state === 'ended' ? (
        <div className="mt-6 space-y-4">
          <label className="block">
            <span className="label">Calling from</span>
            <select className="input mt-1" value={PRESETS.find((p) => p.cli === cli) ? cli : 'custom'} onChange={(e) => e.target.value !== 'custom' && setCli(e.target.value)}>
              {PRESETS.map((p) => (
                <option key={p.cli} value={p.cli}>{p.label}</option>
              ))}
              <option value="custom">Custom…</option>
            </select>
            <input className="input mt-2 font-mono" value={cli} onChange={(e) => setCli(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Language</span>
            <select className="input mt-1" value={lang} onChange={(e) => setLang(e.target.value)}>
              <option value="hinglish">Hinglish</option>
              <option value="hi">Hindi</option>
              <option value="en">English</option>
            </select>
          </label>
          <div>
            <span className="label">Voice source</span>
            <div className="mt-1 grid grid-cols-2 gap-2">
              <button className={mode === 'mic' ? 'btn-primary' : 'btn-outline'} onClick={() => setMode('mic')}>Microphone</button>
              <button className={mode === 'file' ? 'btn-primary' : 'btn-outline'} onClick={() => setMode('file')}>Play a recording</button>
            </div>
            {mode === 'mic' && mics.length > 1 && (
              <select className="input mt-2" value={mic} onChange={(e) => setMic(e.target.value)}>
                <option value="">Default microphone</option>
                {mics.map((m) => (
                  <option key={m.deviceId} value={m.deviceId}>{m.label || 'Microphone'}</option>
                ))}
              </select>
            )}
            {mode === 'file' && (
              <div className="mt-2 space-y-1">
                <input type="file" accept="audio/*" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                <p className="text-xs text-muted">Attacker level L1: a pre-made clip is played into the call once the agent answers. For live voice conversion (L3), pick a virtual cable as the microphone.</p>
              </div>
            )}
          </div>
          {err && <p className="rounded-md bg-red-soft px-3 py-2 text-sm text-red">{err}</p>}
          <button className="btn w-full bg-green py-4 text-base text-white" onClick={dial}>
            {state === 'ended' ? 'Call again' : 'Call'}
          </button>
          {state === 'ended' && <p className="text-center text-sm text-muted">Call ended.</p>}
        </div>
      ) : (
        <div className="mt-10 flex flex-1 flex-col items-center">
          <div className="grid h-28 w-28 place-items-center rounded-full bg-brand-soft">
            <div className="rounded-full bg-brand transition-all" style={{ width: 40 + Math.min(1, level * 3) * 50, height: 40 + Math.min(1, level * 3) * 50, opacity: 0.85 }} />
          </div>
          <p className="mt-6 font-display text-2xl font-bold">{state === 'ringing' ? 'Ringing…' : clock((Date.now() - since) / 1000)}</p>
          <p className="text-sm text-muted">{state === 'ringing' ? 'Waiting for an agent' : 'Connected to customer care'}</p>
          <p className="mt-1 font-mono text-xs text-muted">from {cli} · 8 kHz G.711</p>
          <div className="mt-auto grid w-full grid-cols-2 gap-3 pb-6 pt-10">
            <button className="btn-outline py-4" onClick={toggleMute} disabled={state !== 'live'}>{muted ? 'Unmute' : 'Mute'}</button>
            <button className="btn-danger py-4" onClick={hangup}>Hang up</button>
          </div>
        </div>
      )}
    </div>
  )
}
