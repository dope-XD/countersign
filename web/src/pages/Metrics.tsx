import { api } from '../lib/api'
import { usePoll } from '../lib/events'
import { TopBar } from '../components/ui'

type Bench = {
  set: string
  condition: string
  model?: string
  detect_at_1pct_far?: number
  eer: number
  n_bona: number
  n_spoof: number
  published_eer?: number | null
  false_alarm_amber?: number | null
  detect_amber?: number | null
  detect_red?: number | null
}
type Target = { name: string; target: string; result: string; pass: boolean | null }
type Level = { level: string; description: string; calls: number; approved: number; tiers: Record<string, number>; by_cli?: Record<string, number> }
type Fair = { group: string; n: number; fpr: number; ci: [number, number] }
type Miss = { id: string; level: string; cli_kind?: string; language: string; tier: string; why: string }
type CliKind = 'registered' | 'other'
type GenuineRow = { cli_kind: CliKind; label: string; n: number; k: number; rate: number; ci: [number, number]; executed: number }
type GeneratorRow = { generator: string; levels: string[]; n: number; k: number; rate: number; ci: [number, number]; red: number; ended_green: number }
const GENERATOR: Record<string, string> = {
  xtts: 'XTTS v2 (TTS)',
  f5: 'F5-TTS',
  indicf5: 'IndicF5 (Indian-language TTS)',
  chatterbox: 'Chatterbox (TTS)',
  seedvc: 'Seed-VC (live voice conversion)',
}
type Detection = { level: string; cli_kind: CliKind; spoofed_cli: boolean; n: number; k: number; rate: number; ci: [number, number]; red: number; ended_green: number }
type Report = {
  generated_at: string
  model: Record<string, string>
  benchmarks: Bench[]
  indiacall?: {
    targets: Target[]
    levels: Level[]
    genuine: { calls: number; stepped_up: number; rate: number; by_cli?: GenuineRow[] }
    detection?: Detection[]
    by_generator?: GeneratorRow[]
    first_tier_s?: { p50: number; p95: number }
    latency_ms?: { p50: number; p95: number }
    fairness: Fair[]
    misses: Miss[]
  }
  notes?: string[]
}
type Metrics = { report: Report | null; live: { s1_backend: string; s1_version: string; windows_scored: number; p50_ms: number | null; p95_ms: number | null } }

const CH: Record<string, string> = {
  clean: 'clean',
  g711u: 'G.711 μ-law (PSTN)',
  amrnb_12k2: 'AMR-NB 12.2k (mobile)',
  opus_12k: 'Opus 12k (VoIP)',
  'g711u+loss+noise': 'G.711 + room noise + 3% loss',
  'amrnb_12k2+loss+noise': 'AMR-NB + room noise + 3% loss',
}
const opt = (x?: number | null) => (x != null ? pct(x) : '—')
const pct = (x: number) => `${(x * 100).toFixed(x < 0.1 ? 2 : 1)}%`
const ci = (c: [number, number]) => `[${pct(c[0])}, ${pct(c[1])}]`
const NUMBER: Record<string, string> = { registered: 'registered number', other: 'another number' }

export default function Metrics() {
  const { data } = usePoll(() => api.get<Metrics>('/api/metrics'), 5000)
  const r = data?.report
  const ic = r?.indiacall
  return (
    <div className="min-h-full">
      <TopBar title="Metrics" />
      <main className="mx-auto max-w-5xl space-y-8 p-4 sm:p-6">
        <header>
          <h1 className="text-3xl font-extrabold">How well it works, misses included</h1>
          <p className="mt-1 text-muted">
            Every number here comes from <span className="code">ml/eval/report.py</span> on phone-quality audio.
            {r && <> Generated {new Date(r.generated_at).toLocaleString()}.</>}
          </p>
        </header>

        {!r && (
          <div className="card p-5 text-sm">
            No evaluation report yet. Run <span className="code">python -m ml.eval.report</span> to produce <span className="code">models/metrics.json</span>.
          </div>
        )}

        {ic && (
          <section>
            <h2 className="text-xl font-bold">Targets at the finale</h2>
            <table className="mt-3 w-full text-sm">
              <thead>
                <tr className="border-b border-ink text-left"><th className="py-2 font-semibold">Measure</th><th>Target</th><th>Result</th><th /></tr>
              </thead>
              <tbody>
                {ic.targets.map((t) => (
                  <tr key={t.name} className="border-b border-line">
                    <td className="py-2 pr-2">{t.name}</td>
                    <td className="whitespace-nowrap pr-2">{t.target}</td>
                    <td className="whitespace-nowrap pr-2 font-semibold">{t.result}</td>
                    <td className={t.pass ? 'text-green' : t.pass === false ? 'text-red' : 'text-muted'}>{t.pass ? 'met' : t.pass === false ? 'missed' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {ic && (
          <section className="grid gap-6 lg:grid-cols-2">
            <div>
              <h2 className="text-xl font-bold">IndiaCall by attacker level</h2>
              <table className="mt-3 w-full text-sm">
                <thead>
                  <tr className="border-b border-ink text-left"><th className="py-2">Level</th><th>Calls</th><th>Changes approved</th><th>GREEN / AMBER / RED</th></tr>
                </thead>
                <tbody>
                  {ic.levels.map((l) => (
                    <tr key={l.level} className="border-b border-line" title={l.description}>
                      <td className="py-2 font-semibold">{l.level}</td>
                      <td>{l.calls}</td>
                      <td className={l.approved ? 'font-semibold text-red' : 'text-green'}>{l.approved}</td>
                      <td className="font-mono text-xs">{l.tiers.GREEN || 0} / {l.tiers.AMBER || 0} / {l.tiers.RED || 0}</td>
                    </tr>
                  ))}
                  {ic.genuine.by_cli ? (
                    ic.genuine.by_cli.map((g) => (
                      <tr key={g.cli_kind} className="border-b border-line">
                        <td className="py-2 font-semibold">Genuine<div className="text-xs font-normal text-muted">{NUMBER[g.cli_kind]}</div></td>
                        <td>{g.n}</td>
                        <td colSpan={2}>
                          {g.k} given an extra check ({pct(g.rate)} <span className="font-mono text-xs text-muted">{ci(g.ci)}</span>)
                          {g.cli_kind === 'registered' ? <div className="text-xs text-muted">target 5% or fewer</div> : <div className="text-xs text-muted">expected: an unknown number gets a liveness check</div>}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr className="border-b border-line">
                      <td className="py-2 font-semibold">Genuine</td>
                      <td>{ic.genuine.calls}</td>
                      <td colSpan={2}>{ic.genuine.stepped_up} given an extra check ({pct(ic.genuine.rate)})</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div>
              <h2 className="text-xl font-bold">False alarms by group</h2>
              <p className="text-xs text-muted">Genuine calls from the registered number stepped up, with 95% Wilson intervals. Target: no group above 2× overall.</p>
              <div className="mt-3 space-y-2">
                {ic.fairness.map((f) => (
                  <div key={f.group} className="text-sm">
                    <div className="flex justify-between"><span>{f.group} <span className="text-muted">(n={f.n})</span></span><span className="font-mono">{pct(f.fpr)} [{pct(f.ci[0])}, {pct(f.ci[1])}]</span></div>
                    <div className="relative mt-1 h-2 rounded bg-line/60">
                      <div className="absolute h-2 rounded bg-brand/30" style={{ left: `${f.ci[0] * 100}%`, width: `${Math.max(0.5, (f.ci[1] - f.ci[0]) * 100)}%` }} />
                      <div className="absolute h-2 w-1 rounded bg-brand" style={{ left: `${f.fpr * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {ic?.detection && ic.detection.length > 0 && (
          <section>
            <h2 className="text-xl font-bold">Detection only</h2>
            <p className="text-xs text-muted">
              Attack calls the agent saw as AMBER or RED, ignoring whether app approval later stopped them. Ended GREEN means a voice-only bank would have approved them.
              With the registered number spoofed there is no caller-ID flag, so the tier comes from the voice signals alone.
            </p>
            <table className="mt-3 w-full text-sm">
              <thead>
                <tr className="border-b border-ink text-left"><th className="py-2">Level</th><th>Calling from</th><th>Calls</th><th>Reached AMBER or RED</th><th>RED</th><th>Ended GREEN</th></tr>
              </thead>
              <tbody>
                {ic.detection.map((d) => (
                  <tr key={`${d.level}-${d.cli_kind}`} className="border-b border-line">
                    <td className="py-2 font-semibold">{d.level}</td>
                    <td>{d.spoofed_cli ? (d.level === 'L4' ? 'registered number (spoofed, SIM swap)' : 'registered number (spoofed)') : 'own number (FRI High)'}</td>
                    <td>{d.n}</td>
                    <td>{pct(d.rate)} <span className="font-mono text-xs text-muted">{ci(d.ci)}</span></td>
                    <td>{d.red}</td>
                    <td className={d.ended_green ? 'font-semibold text-red' : 'text-green'}>{d.ended_green}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {ic?.by_generator && ic.by_generator.length > 0 && (
          <section>
            <h2 className="text-xl font-bold">Detection by clone generator</h2>
            <p className="text-xs text-muted">
              Attacks that spoof the registered number, so only the voice signals can raise the tier. Ended GREEN means the voice signals missed it; app approval still
              stood in the way.
            </p>
            <table className="mt-3 w-full text-sm">
              <thead>
                <tr className="border-b border-ink text-left"><th className="py-2">Generator</th><th>Levels</th><th>Calls</th><th>Reached AMBER or RED</th><th>RED</th><th>Ended GREEN</th></tr>
              </thead>
              <tbody>
                {ic.by_generator.map((g) => (
                  <tr key={g.generator} className="border-b border-line">
                    <td className="py-2 font-semibold">{GENERATOR[g.generator] || g.generator}</td>
                    <td>{g.levels.join(', ')}</td>
                    <td>{g.n}</td>
                    <td>{pct(g.rate)} <span className="font-mono text-xs text-muted">{ci(g.ci)}</span></td>
                    <td>{g.red}</td>
                    <td className={g.ended_green ? 'font-semibold text-red' : 'text-green'}>{g.ended_green}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {r && r.benchmarks.length > 0 && (
          <section>
            <h2 className="text-xl font-bold">Detector (S1) error on public test sets</h2>
            <p className="text-xs text-muted">
              S1 alone, model <span className="font-mono">{r.model.s1}</span>; the product never acts on S1 alone. EER, lower is better. The tier columns
              are what the engine does with one window: the share of real clips it would raise to AMBER, and of fake clips it raises to AMBER and to RED.
            </p>
            <table className="mt-3 w-full text-sm">
              <thead>
                <tr className="border-b border-ink text-left">
                  <th className="py-2">Test set</th><th>Channel</th><th>EER</th><th>Real raised to AMBER</th><th>Fakes at AMBER</th><th>Fakes at RED</th><th>Caught at 1% false alarms</th><th>Published</th><th>n (real / fake)</th>
                </tr>
              </thead>
              <tbody>
                {r.benchmarks.map((b, i) => (
                  <tr key={i} className="border-b border-line">
                    <td className="py-2">{b.set}</td>
                    <td>{CH[b.condition] || b.condition}</td>
                    <td className="font-semibold">{pct(b.eer)}</td>
                    <td>{opt(b.false_alarm_amber)}</td>
                    <td>{opt(b.detect_amber)}</td>
                    <td>{opt(b.detect_red)}</td>
                    <td>{b.detect_at_1pct_far != null ? pct(b.detect_at_1pct_far) : '—'}</td>
                    <td className="text-muted">{b.published_eer != null ? pct(b.published_eer) : '—'}</td>
                    <td className="font-mono text-xs">{b.n_bona} / {b.n_spoof}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {ic && ic.misses.length > 0 && (
          <section>
            <h2 className="text-xl font-bold">Every miss</h2>
            <table className="mt-3 w-full text-sm">
              <thead><tr className="border-b border-ink text-left"><th className="py-2">Call</th><th>Level</th><th>Language</th><th>Tier</th><th>Why</th></tr></thead>
              <tbody>
                {ic.misses.map((m) => (
                  <tr key={m.id} className="border-b border-line">
                    <td className="py-2 font-mono text-xs">{m.id}</td><td>{m.level}{m.cli_kind && <div className="text-xs text-muted">{NUMBER[m.cli_kind]}</div>}</td><td>{m.language}</td><td>{m.tier}</td><td className="text-muted">{m.why}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <section className="card grid gap-4 p-5 sm:grid-cols-4">
          <Stat label="S1 model (live)" value={data ? `${data.live.s1_backend}` : '—'} sub={data?.live.s1_version} />
          <Stat label="Windows scored" value={data ? String(data.live.windows_scored) : '—'} />
          <Stat label="Latency p50" value={data?.live.p50_ms != null ? `${data.live.p50_ms.toFixed(0)} ms` : '—'} />
          <Stat label="Latency p95 (target ≤300)" value={data?.live.p95_ms != null ? `${data.live.p95_ms.toFixed(0)} ms` : '—'} />
        </section>

        {r?.notes && (
          <section className="text-sm text-muted">
            <h2 className="text-base font-bold text-ink">Notes</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {r.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </section>
        )}
      </main>
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="mt-1 font-display text-2xl font-bold">{value}</div>
      {sub && <div className="truncate text-xs text-muted">{sub}</div>}
    </div>
  )
}
