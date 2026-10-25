// The dark act: Mummy's call, the hour on the line, and why our first version wasn't good enough.
import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Bg, Card, CountUp, inr, Phone, Pop, Sfx, SmallPrint, Strike, Words} from '../kit/motion';
import {IncomingCall, InCall, PayScreen} from '../kit/screens';
import {mix, ramp, useScene, EASE_IO} from '../kit/time';
import {Said} from '../kit/type';
import {C, FONT} from '../theme';

const STORY = 'A typical case, retold. Illustrative.';

const Rings: React.FC<{x: number; y: number; until: number}> = ({x, y, until}) => {
  const {t} = useScene();
  if (t > until + 1.2) return null;
  return (
    <>
      {[0, 0.4, 0.8].map((d) => {
        const ph = ((t + d) % 1.2) / 1.2;
        const fade = t > until ? 1 - ramp(t, until, until + 1.2) : 1;
        return (
          <div
            key={d}
            style={{
              position: 'absolute',
              left: x - 200,
              top: y - 200,
              width: 400,
              height: 400,
              borderRadius: 999,
              border: `2px solid ${C.nightText}`,
              opacity: (1 - ph) * 0.25 * fade,
              transform: `scale(${mix(0.9, 2.4, ph)})`,
            }}
          />
        );
      })}
    </>
  );
};

export const S01: React.FC = () => {
  const {t, cue, out} = useScene();
  const pick = cue('The man says');
  const slide = ramp(t, pick - 0.3, pick + 0.6, EASE_IO);
  const shake = t < pick ? Math.sin(t * 60) * 1.4 * (Math.floor(t * 2) % 2) : 0;
  const x = mix(960 - 190, 330, slide);
  const secs = Math.max(0, t - pick);
  return (
    <AbsoluteFill>
      <Bg dark />
      <Rings x={x + 190} y={540} until={pick} />
      <Pop at={0} out={out} from="scale" style={{left: 0, top: 0}}>
        <Phone w={380} screen="#0E1217" style={{left: x, top: 540 - 399, transform: `rotate(${shake}deg)`}}>
          {t < pick ? (
            <IncomingCall name="Unknown number" number="+91 87••• ••214" sub="Incoming call" />
          ) : (
            <InCall name="Unknown number" time={`00:${String(Math.floor(secs)).padStart(2, '0')}`} />
          )}
        </Phone>
      </Pop>
      <div style={{position: 'absolute', left: 800, top: 200, width: 1040}}>
        <Pop at={pick} out={out} from="none" style={{top: 0}}>
          <Said hi="मैं CBI से बोल रहा हूँ।" en="I'm calling from the CBI." at={pick} />
        </Pop>
        <Pop at={cue('a parcel')} out={out} from="none" style={{top: 230}}>
          <Said hi="आपके नाम पे एक पार्सल मिला है।" en="There's a parcel in your name." at={cue('a parcel')} />
        </Pop>
        <Pop at={cue('with drugs')} out={out} from="none" style={{top: 460}}>
          <Said hi="उसमें ड्रग्स हैं।" en="It has drugs in it." at={cue('with drugs')} />
        </Pop>
      </div>
      <SmallPrint text={STORY} dark />
      <Sfx name="ring" at={0} volume={0.5} />
      <Sfx name="type" at={pick} volume={0.25} />
      <Sfx name="type" at={cue('a parcel')} volume={0.25} />
      <Sfx name="type" at={cue('with drugs')} volume={0.25} />
    </AbsoluteFill>
  );
};

export const S02: React.FC = () => {
  const {t, cue, out} = useScene();
  const a = Math.min(cue('stay on the line'), 0.25);
  const b = cue('tell no one');
  const pay = cue('he asks her to move');
  const sent = cue('She does');
  const up = ramp(t, pay - 0.5, pay + 0.3, EASE_IO);
  return (
    <AbsoluteFill>
      <Bg dark />
      <div style={{position: 'absolute', left: 0, right: 0, top: 210, display: 'flex', justifyContent: 'center', gap: 34, transform: `translateY(${-up * 60}px)`, opacity: 1 - up, filter: up > 0 ? `blur(${up * 12}px)` : undefined}}>
        <Words text="Stay on the line." at={a} size={92} color={C.nightText} />
        <Words text="Tell no one." at={b} size={92} color={C.nightText} />
      </div>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 420,
          textAlign: 'center',
          fontFamily: FONT,
          color: C.nightText,
          opacity: ramp(t, b, b + 0.5) * (1 - up),
          transform: `translateY(${-up * 60}px)`,
          filter: up > 0 ? `blur(${up * 12}px)` : undefined,
        }}
      >
        <div style={{fontSize: 30, color: C.nightMuted, fontWeight: 500, marginBottom: 6}}>On the call</div>
        <CountUp from={0} to={58 * 60} a={b} b={pay - 0.4} fmt={(v) => `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(Math.floor(v % 60)).padStart(2, '0')}`} style={{fontSize: 250, fontWeight: 700, letterSpacing: '-0.04em'}} />
      </div>
      <Pop at={pay} out={out} from="up" dist={120} style={{left: 960 - 190, top: 120}}>
        <Phone w={380} screen="#fff">
          <PayScreen to="The 'safe account' he gave her" amount={inr(mix(0, 480000, ramp(t, pay + 0.3, pay + 1.6)))} sent={t > sent ? 1 : 0} />
        </Phone>
      </Pop>
      <Pop at={sent + 0.5} out={out} from="left" style={{left: 1240, top: 470}}>
        <div style={{fontFamily: FONT, fontSize: 110, fontWeight: 700, color: C.nightText, letterSpacing: '-0.04em'}}>Gone.</div>
      </Pop>
      <SmallPrint text={STORY} dark />
      <Sfx name="tick" at={b} volume={0.3} />
      <Sfx name="whoosh" at={pay} volume={0.4} />
      <Sfx name="tap" at={sent} volume={0.6} />
    </AbsoluteFill>
  );
};

const Mark: React.FC<{w: string; at: number}> = ({w, at}) => {
  const {t} = useScene();
  const p = ramp(t, at, at + 0.4);
  return (
    <span style={{position: 'relative', display: 'inline-block'}}>
      <span style={{position: 'absolute', left: -4, right: -4, top: 4, bottom: 2, background: C.amberBright, opacity: 0.85, borderRadius: 6, transformOrigin: 'left', transform: `scaleX(${p})`}} />
      <span style={{position: 'relative', color: p > 0.5 ? C.night : undefined}}>{w}</span>
    </span>
  );
};

const Said2: React.FC<{parts: (string | [string])[]; at: number}> = ({parts, at}) => (
  <div style={{fontSize: 36, lineHeight: 1.45, fontWeight: 500}}>
    {parts.map((p, i) => (typeof p === 'string' ? <span key={i}>{p}</span> : <Mark key={i} w={p[0]} at={at + i * 0.08} />))}
  </div>
);

export const S03: React.FC = () => {
  const {t, cue, out} = useScene();
  const words = Math.min(cue('listened for words'), 0.25);
  const mark = cue('like police and OTP');
  const bank = cue('Then a real bank called');
  const again = cue('So we started again');
  const flag = (at: number, wrong: boolean) => {
    const p = ramp(t, at, at + 0.35);
    const shake = wrong && t > at + 0.6 && t < at + 1.2 ? Math.sin(t * 70) * 6 : 0;
    return (
      <div style={{display: 'flex', gap: 16, alignItems: 'center', marginTop: 26, opacity: p, transform: `scale(${mix(0.8, 1, p)}) translateX(${shake}px)`, transformOrigin: 'left'}}>
        <div style={{background: C.redSoft, color: C.red, fontWeight: 700, fontSize: 28, borderRadius: 99, padding: '10px 22px'}}>⚠ Scam</div>
        {wrong && <div style={{color: '#FF8A80', fontSize: 28, fontWeight: 650, opacity: ramp(t, at + 0.6, at + 1)}}>A real bank. False alarm.</div>}
      </div>
    );
  };
  return (
    <AbsoluteFill>
      <Bg dark />
      <div style={{position: 'absolute', left: 140, top: 130}}>
        <div style={{position: 'relative'}}>
          <Words text="Listening for words." at={words} size={84} color={C.nightText} out={out} />
          <Strike at={again} />
        </div>
      </div>
      <Pop at={words + 0.3} out={again + 0.3} from="up" exitTo="down" style={{left: 140, top: 330}}>
        <Card dark style={{width: 780, padding: 40}}>
          <div style={{fontSize: 24, color: C.nightMuted, fontWeight: 600, marginBottom: 14}}>Your bank, a real call</div>
          <Said2 parts={['"We will never ask for your ', ['OTP'], '. If anyone says they are ', ['police'], ', hang up and call us."']} at={mark} />
          {flag(bank, true)}
        </Card>
      </Pop>
      <Pop at={words + 0.45} out={again + 0.35} from="up" exitTo="down" style={{left: 1000, top: 330}}>
        <Card dark style={{width: 780, padding: 40}}>
          <div style={{fontSize: 24, color: C.nightMuted, fontWeight: 600, marginBottom: 14}}>The CBI call, a scam</div>
          <Said2 parts={['"Share the ', ['OTP'], ' to verify, or the ', ['police'], ' will come to arrest you."']} at={mark + 0.25} />
          {flag(bank, false)}
        </Card>
      </Pop>
      <Sfx name="whoosh" at={words + 0.3} volume={0.35} />
      <Sfx name="amber" at={bank} volume={0.4} />
      <Sfx name="whoosh" at={again} volume={0.4} />
    </AbsoluteFill>
  );
};
