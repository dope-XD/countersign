// What we read before building, and what we measured. Every number here is from docs/RESULTS.md or the named paper.
import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Bg, Brand, Card, Chip, CountUp, Pop, Sfx, SmallPrint, Words} from '../kit/motion';
import {EASE_IO, mix, ramp, useScene} from '../kit/time';
import {C, FONT} from '../theme';

const PAPERS = [
  {title: 'PreScam', sub: 'arXiv, 2026'},
  {title: 'ICFD-31k', sub: 'IJCAI, 2026'},
  {title: 'Scam Detection', sub: 'Google'},
  {title: 'Voice phishing protection', sub: 'Samsung'},
  {title: 'On-device scam detection', sub: 'DeepMind and GovTech Singapore'},
];

const Paper: React.FC<{title: string; sub: string}> = ({title, sub}) => (
  <div style={{width: 300, height: 390, background: '#fff', borderRadius: 10, boxShadow: '0 24px 60px rgba(20,32,43,0.14)', padding: 26, fontFamily: FONT}}>
    <div style={{fontSize: 15, color: C.muted, fontWeight: 600}}>{sub}</div>
    <div style={{fontSize: 27, fontWeight: 750, color: C.ink, marginTop: 8, lineHeight: 1.15, letterSpacing: '-0.02em'}}>{title}</div>
    {Array.from({length: 9}).map((_, i) => (
      <div key={i} style={{height: 9, borderRadius: 9, background: C.greySoft, marginTop: i === 0 ? 26 : 13, width: `${[100, 92, 97, 80, 100, 88, 95, 70, 60][i]}%`}} />
    ))}
  </div>
);

export const S07: React.FC = () => {
  const {t, cue, out} = useScene();
  const read = cue('We read up');
  const big = cue('Google and Samsung');
  const study = cue('A 2026 study');
  const ours = cue('So we fine-tuned one');
  const phone = cue('It runs on a six-gigabyte phone');
  const hl = ramp(t, big - 0.2, big + 0.3);
  const papersOut = ramp(t, study - 0.4, study);
  const chartOut = ramp(t, ours - 0.3, ours + 0.2);
  const bar = (v: number, from: number, at: number) => mix(from, v, ramp(t, at, at + 1.1, EASE_IO));
  const scale = (v: number) => ((v - 50) / 50) * 1100; // 50 = guessing, 100 = perfect
  const squares = 310; // one square = 100 calls
  return (
    <AbsoluteFill>
      <Bg />
      <Brand />
      {/* the reading pile: Google's and Samsung's light up, then PreScam's */}
      <div style={{position: 'absolute', left: 140, top: 150, opacity: 1 - hl}}>
        <Words text="We read up before we built." at={read} size={80} weight={700} />
      </div>
      <div style={{position: 'absolute', left: 140, top: 150, opacity: t < big ? 0 : 1 - papersOut}}>
        <Words text="Google and Samsung both check calls on the phone." at={big + 0.1} size={64} weight={700} style={{width: 1640}} />
      </div>
      <div style={{position: 'absolute', inset: 0, opacity: 1 - papersOut, filter: papersOut > 0 ? `blur(${papersOut * 12}px)` : undefined}}>
        {PAPERS.map((p, i) => {
          const a = read + 0.1 + i * 0.06;
          const k = ramp(t, a, a + 0.5);
          const fan = ramp(t, a + 0.2, a + 0.9, EASE_IO);
          const x = mix(810, 140 + i * 340, fan);
          const rot = mix((i - 2) * 4, (i - 2) * 1.2, fan);
          const lit = i === 2 || i === 3;
          return (
            <div
              key={p.title}
              style={{
                position: 'absolute',
                left: x,
                top: mix(1000, 340, k) - (lit ? 30 * hl : 0),
                transform: `rotate(${rot * (1 - hl)}deg) scale(${lit ? 1 + 0.06 * hl : 1})`,
                opacity: k * (lit ? 1 : 1 - 0.65 * hl),
              }}
            >
              <Paper {...p} />
              {lit && (
                <div style={{marginTop: 26, fontFamily: FONT, fontSize: 25, lineHeight: 1.3, color: C.ink, fontWeight: 600, width: 300, opacity: ramp(t, big + 0.5, big + 0.9)}}>
                  {i === 2 ? 'Judges the conversation, on the phone.' : 'A model trained on police records of scam calls, on the phone.'}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {/* PreScam: fine-tuned vs chatbots */}
      <div style={{position: 'absolute', inset: 0, opacity: (t > study - 0.3 ? 1 : 0) * (1 - chartOut), filter: chartOut > 0 ? `blur(${chartOut * 12}px)` : undefined}}>
        <div style={{position: 'absolute', left: 140, top: 150}}>
          <Words text="Small and trained beats big and general." at={study} size={64} weight={700} />
        </div>
        <Pop at={study + 0.2} from="up" style={{left: 140, top: 330}}>
          <Card style={{width: 1640, padding: '44px 54px'}}>
            <div style={{fontSize: 26, color: C.muted, fontWeight: 600}}>PreScam, 2026 · 11,500 real scam calls · how well each model spots a scam coming (50 is a guess)</div>
            {[
              {name: 'Small model, fine-tuned', lo: 83.4, hi: 83.4, color: C.brand, at: study + 0.5, label: '83'},
              {name: 'Chatbots, asked directly', lo: 63, hi: 70, color: C.line, at: study + 0.8, label: '63 to 70'},
            ].map((r) => (
              <div key={r.name} style={{display: 'flex', alignItems: 'center', marginTop: 40}}>
                <div style={{width: 390, fontSize: 30, fontWeight: 650}}>{r.name}</div>
                <div style={{position: 'relative', height: 64, width: 1100}}>
                  <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: scale(bar(r.lo, 50, r.at)), background: r.color, borderRadius: 12}} />
                  {r.hi > r.lo && <div style={{position: 'absolute', left: scale(r.lo), top: 0, bottom: 0, width: scale(r.hi) - scale(r.lo), background: r.color, opacity: 0.45 * ramp(t, r.at + 1, r.at + 1.4), borderRadius: '0 12px 12px 0'}} />}
                  <div style={{position: 'absolute', left: scale(bar(r.hi, 50, r.at)) + 20, top: 8, fontSize: 40, fontWeight: 750, color: C.ink, fontVariantNumeric: 'tabular-nums'}}>{r.label}</div>
                </div>
              </div>
            ))}
          </Card>
        </Pop>
      </div>
      {/* ours: ICFD-31k */}
      {t > ours - 0.3 && (
        <AbsoluteFill>
          <div style={{position: 'absolute', left: 140, top: 150}}>
            <Words text="So we trained ours on Indian bank calls." at={ours} size={64} weight={700} out={out} />
          </div>
          <div style={{position: 'absolute', left: 140, top: 300, display: 'grid', gridTemplateColumns: 'repeat(31, 22px)', gap: 8, opacity: 1 - ramp(t, out, out + 0.4)}}>
            {Array.from({length: squares}).map((_, i) => {
              const at = ours + 0.2 + (i / squares) * 1.8;
              const k = ramp(t, at, at + 0.25);
              return <div key={i} style={{width: 22, height: 22, borderRadius: 5, background: C.brand, opacity: 0.15 + 0.85 * k, transform: `scale(${mix(0.4, 1, k)})`}} />;
            })}
          </div>
          <div style={{position: 'absolute', left: 1120, top: 300, fontFamily: FONT, opacity: ramp(t, ours + 0.2, ours + 0.6) * (1 - ramp(t, out, out + 0.4))}}>
            <CountUp from={0} to={31000} a={ours + 0.2} b={ours + 2} fmt={(v) => Math.round(v).toLocaleString('en-IN')} style={{fontSize: 150, fontWeight: 750, letterSpacing: '-0.04em', color: C.ink}} />
            <div style={{fontSize: 34, color: C.muted, fontWeight: 600, marginTop: 4}}>bank calls from India, scam and genuine</div>
            <div style={{fontSize: 26, color: C.muted, marginTop: 10}}>ICFD-31k · English and Hinglish · one square = 100 calls</div>
          </div>
          <div style={{position: 'absolute', left: 140, top: 760, display: 'flex', gap: 22}}>
            <Pop at={phone} out={out} from="up" style={{position: 'relative'}}>
              <Chip text="Runs on a 6 GB phone" fg={C.brand} bg={C.brandSoft} size={34} />
            </Pop>
            <Pop at={phone + 0.25} out={out} from="up" style={{position: 'relative'}}>
              <Chip text="One 798 MB download, then no internet needed" fg={C.brand} bg={C.brandSoft} size={34} />
            </Pop>
          </div>
        </AbsoluteFill>
      )}
      <SmallPrint text="Sources: PreScam, arXiv 2605.12243 · ICFD-31k, IJCAI 2026 · Google and Samsung product announcements." />
      <Sfx name="whoosh" at={read + 0.25} volume={0.35} />
      <Sfx name="whoosh" at={big} volume={0.3} />
      <Sfx name="whoosh" at={study} volume={0.3} />
      <Sfx name="rise" at={ours + 0.2} volume={0.35} />
      <Sfx name="pop" at={phone} volume={0.35} />
    </AbsoluteFill>
  );
};

const Waffle: React.FC<{lit: number; color: string}> = ({lit, color}) => (
  <div style={{display: 'grid', gridTemplateColumns: 'repeat(10, 36px)', gap: 11}}>
    {Array.from({length: 100}).map((_, i) => {
      const on = Math.max(0, Math.min(1, lit - i));
      return <div key={i} style={{width: 36, height: 36, borderRadius: 99, background: on > 0 ? color : C.greySoft, opacity: on > 0 ? 0.3 + 0.7 * on : 1}} />;
    })}
  </div>
);

export const S08: React.FC = () => {
  const {t, cue, out} = useScene();
  const head = cue('We tested it');
  const old = cue('Our old version');
  const now = cue('This one flags');
  const catches = cue('It catches 88');
  const kit = cue('and gets 28');
  // genuine calls flagged amber: old keyword path 50.1%, now 2.3% (RESULTS.md, ICFD "Clear Normal")
  const lit = t < now ? mix(0, 50.1, ramp(t, old, old + 1)) : mix(50.1, 2.3, ramp(t, now, now + 1.2, EASE_IO));
  const pct = t < now ? 50.1 * ramp(t, old, old + 1) : mix(50.1, 2.3, ramp(t, now, now + 1.2, EASE_IO));
  const ring = 87.8 * ramp(t, catches, catches + 1.2, EASE_IO);
  const R = 120;
  const L = 2 * Math.PI * R;
  return (
    <AbsoluteFill>
      <Bg />
      <Brand />
      <div style={{position: 'absolute', left: 140, top: 140}}>
        <Words text="Tested on calls it never trained on." at={head} size={64} weight={700} out={out} />
      </div>
      <Pop at={head + 0.3} out={out} from="up" style={{left: 140, top: 300}}>
        <Card style={{width: 860, height: 620, padding: 50}}>
          <div style={{fontSize: 30, fontWeight: 650, color: C.muted}}>Genuine calls it wrongly flagged</div>
          <div style={{display: 'flex', alignItems: 'center', gap: 50, marginTop: 34}}>
            <Waffle lit={lit} color={lit > 8 ? C.amberBright : C.green} />
            <div style={{opacity: ramp(t, old, old + 0.3)}}>
              <div style={{fontSize: 108, fontWeight: 800, letterSpacing: '-0.05em', color: lit > 8 ? C.amber : C.green, fontVariantNumeric: 'tabular-nums'}}>{pct.toFixed(1)}%</div>
              <div style={{fontSize: 30, fontWeight: 650, color: C.ink}}>{t < now ? 'Our old version' : 'This one'}</div>
              <div style={{fontSize: 24, color: C.muted, marginTop: 6, opacity: ramp(t, now + 1, now + 1.4)}}>was 50.1%</div>
            </div>
          </div>
        </Card>
      </Pop>
      <Pop at={catches} out={out} from="right" style={{left: 1040, top: 300}}>
        <Card style={{width: 740, height: 300, padding: 40, display: 'flex', alignItems: 'center', gap: 40}}>
          <svg width={2 * R + 30} height={2 * R + 30} viewBox={`0 0 ${2 * R + 30} ${2 * R + 30}`} style={{transform: 'scale(0.85)', margin: -20}}>
            <circle cx={R + 15} cy={R + 15} r={R} stroke={C.greySoft} strokeWidth={26} fill="none" />
            <circle cx={R + 15} cy={R + 15} r={R} stroke={C.brand} strokeWidth={26} fill="none" strokeLinecap="round" strokeDasharray={L} strokeDashoffset={L * (1 - ring / 100)} transform={`rotate(-90 ${R + 15} ${R + 15})`} />
            <text x={R + 15} y={R + 32} textAnchor="middle" fontFamily={FONT} fontSize={58} fontWeight={800} fill={C.ink}>
              {ring.toFixed(0)}%
            </text>
          </svg>
          <div>
            <div style={{fontSize: 34, fontWeight: 700, color: C.ink, lineHeight: 1.2}}>of scam calls caught</div>
            <div style={{fontSize: 24, color: C.muted, marginTop: 10}}>94% before. We gave up a little here to cut false alarms.</div>
          </div>
        </Card>
      </Pop>
      <Pop at={kit} out={out} from="right" style={{left: 1040, top: 640}}>
        <Card style={{width: 740, height: 280, padding: 36}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}>
            <div style={{fontSize: 30, fontWeight: 650, color: C.muted}}>Our spot-check kit</div>
            <div style={{fontSize: 54, fontWeight: 800, color: C.ink, fontVariantNumeric: 'tabular-nums'}}>
              <CountUp from={0} to={28} a={kit + 0.2} b={kit + 1.6} /> / 30
            </div>
          </div>
          <div style={{display: 'grid', gridTemplateColumns: 'repeat(15, 36px)', gap: 8, marginTop: 22}}>
            {Array.from({length: 30}).map((_, i) => {
              const miss = i === 22 || i === 27; // text_03 (an Instagram phish) and voice_ai_03
              const k = ramp(t, kit + 0.2 + i * 0.045, kit + 0.4 + i * 0.045);
              return (
                <div key={i} style={{width: 36, height: 36, borderRadius: 8, background: k < 0.5 ? C.greySoft : miss ? C.red : C.green, color: '#fff', display: 'grid', placeItems: 'center', fontSize: 20, fontWeight: 800, transform: `scale(${mix(0.6, 1, k)})`}}>
                  {k > 0.5 ? (miss ? '✕' : '✓') : ''}
                </div>
              );
            })}
          </div>
          <div style={{fontSize: 22, color: C.muted, marginTop: 18, opacity: ramp(t, kit + 1.6, kit + 2)}}>Missed: an Instagram text and one computer-made voice.</div>
        </Card>
      </Pop>
      <SmallPrint text="ICFD-31k held-out calls: 1,019 genuine, 4,499 scam. Flagged = amber or red. Kit: 30 public samples we put together (data/kit). All in docs/RESULTS.md." />
      <Sfx name="whoosh" at={head + 0.3} volume={0.3} />
      <Sfx name="tick" at={old} volume={0.35} />
      <Sfx name="down" at={now} volume={0.45} />
      <Sfx name="rise" at={catches} volume={0.3} />
      <Sfx name="type" at={kit + 0.2} volume={0.3} />
    </AbsoluteFill>
  );
};
