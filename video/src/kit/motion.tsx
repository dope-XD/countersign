import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig} from 'remotion';
import {C, FONT} from '../theme';
import {EASE_IN, mix, ramp, useScene} from './time';

type Pos = React.CSSProperties;

/** Words that rise into focus one after another (the reference's caption move), and blur away at `out`. */
export const Words: React.FC<{
  text: string;
  at: number;
  out?: number;
  size?: number;
  weight?: number;
  color?: string;
  style?: Pos;
  stagger?: number;
  font?: string;
  accent?: {words: string[]; color: string};
}> = ({text, at, out, size = 84, weight = 650, color = C.ink, style, stagger = 0.07, font = FONT, accent}) => {
  const {t} = useScene();
  const q = out === undefined ? 0 : ramp(t, out, out + 0.4, EASE_IN);
  const words = text.split(' ');
  return (
    <div
      style={{
        fontFamily: font,
        fontSize: size,
        fontWeight: weight,
        letterSpacing: '-0.035em',
        lineHeight: 1.08,
        color,
        display: 'flex',
        flexWrap: 'wrap',
        columnGap: '0.26em',
        opacity: 1 - q,
        filter: q > 0 ? `blur(${q * 14}px)` : undefined,
        transform: `translateY(${-q * 24}px)`,
        ...style,
      }}
    >
      {words.map((w, i) => {
        const p = ramp(t, at + i * stagger, at + i * stagger + 0.55);
        const hot = accent?.words.includes(w.replace(/[.,!?]/g, ''));
        return (
          <span
            key={i}
            style={{
              display: 'inline-block',
              opacity: p,
              transform: `translateY(${(1 - p) * 0.45}em)`,
              filter: p < 1 ? `blur(${(1 - p) * 12}px)` : undefined,
              color: hot ? accent!.color : undefined,
            }}
          >
            {w}
          </span>
        );
      })}
    </div>
  );
};

/** Enter with a soft spring-like ease from a side, with motion blur; leave the same way at `out`. */
export const Pop: React.FC<{
  at: number;
  out?: number;
  from?: 'up' | 'down' | 'left' | 'right' | 'scale' | 'none';
  dist?: number;
  dur?: number;
  style?: Pos;
  children: React.ReactNode;
  exitTo?: 'up' | 'down' | 'left' | 'right' | 'blur';
}> = ({at, out, from = 'up', dist = 60, dur = 0.7, style, children, exitTo = 'blur'}) => {
  const {t} = useScene();
  const p = ramp(t, at, at + dur);
  const q = out === undefined ? 0 : ramp(t, out, out + 0.45, EASE_IN);
  if (p <= 0 || q >= 1) return null;
  const d = (1 - p) * dist;
  const v = (p > 0 && p < 1 ? (1 - p) : 0) * 10; // blur while moving
  let tf = '';
  if (from === 'up') tf = `translateY(${d}px)`;
  if (from === 'down') tf = `translateY(${-d}px)`;
  if (from === 'left') tf = `translateX(${-d}px)`;
  if (from === 'right') tf = `translateX(${d}px)`;
  if (from === 'scale') tf = `scale(${mix(0.86, 1, p)})`;
  const e = q * 80;
  if (exitTo === 'up') tf += ` translateY(${-e}px)`;
  if (exitTo === 'down') tf += ` translateY(${e}px)`;
  if (exitTo === 'left') tf += ` translateX(${-e * 2}px)`;
  if (exitTo === 'right') tf += ` translateX(${e * 2}px)`;
  return (
    <div style={{position: 'absolute', opacity: p * (1 - q), transform: tf, filter: v + q * 14 > 0.3 ? `blur(${v + q * 14}px)` : undefined, ...style}}>
      {children}
    </div>
  );
};

/** A line drawn through text from left to right. */
export const Strike: React.FC<{at: number; color?: string; thick?: number; top?: string}> = ({at, color = C.nightText, thick = 7, top = '54%'}) => {
  const {t} = useScene();
  const p = ramp(t, at, at + 0.45);
  return <div style={{position: 'absolute', left: 0, top, height: thick, width: `${p * 100}%`, background: color, borderRadius: thick}} />;
};

/** An accent line sweeping in under text. */
export const Underline: React.FC<{at: number; color?: string; thick?: number; bottom?: number}> = ({at, color = C.brand, thick = 6, bottom = -10}) => {
  const {t} = useScene();
  const p = ramp(t, at, at + 0.5);
  return <div style={{position: 'absolute', left: 0, bottom, height: thick, width: `${p * 100}%`, background: color, borderRadius: thick}} />;
};

export const Card: React.FC<{style?: Pos; dark?: boolean; children: React.ReactNode}> = ({style, dark, children}) => (
  <div
    style={{
      background: dark ? C.nightCard : C.white,
      border: `1px solid ${dark ? C.nightLine : 'rgba(20,32,43,0.06)'}`,
      borderRadius: 26,
      boxShadow: dark ? '0 30px 80px rgba(0,0,0,0.45)' : '0 30px 70px rgba(20,32,43,0.10), 0 6px 18px rgba(20,32,43,0.06)',
      padding: 30,
      fontFamily: FONT,
      color: dark ? C.nightText : C.ink,
      ...style,
    }}
  >
    {children}
  </div>
);

export const Chip: React.FC<{text: string; fg?: string; bg?: string; dot?: boolean; size?: number; style?: Pos}> = ({
  text,
  fg = C.ink,
  bg = C.white,
  dot = true,
  size = 30,
  style,
}) => (
  <div
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 14,
      padding: `${size * 0.45}px ${size * 0.8}px`,
      borderRadius: 999,
      background: bg,
      color: fg,
      fontFamily: FONT,
      fontWeight: 600,
      fontSize: size,
      letterSpacing: '-0.01em',
      boxShadow: '0 10px 30px rgba(20,32,43,0.08)',
      whiteSpace: 'nowrap',
      ...style,
    }}
  >
    {dot && <span style={{width: size * 0.38, height: size * 0.38, borderRadius: 99, background: fg}} />}
    {text}
  </div>
);

/** A phone: bezel, island and a screen for the children. `w` sets the size; the height follows a 19.5:9 screen. */
export const Phone: React.FC<{w?: number; screen?: string; style?: Pos; children?: React.ReactNode; tilt?: number}> = ({
  w = 400,
  screen = C.paper,
  style,
  children,
  tilt = 0,
}) => {
  const h = w * 2.1;
  const b = w * 0.032;
  return (
    <div
      style={{
        position: 'absolute',
        width: w,
        height: h,
        borderRadius: w * 0.16,
        background: '#0A0D11',
        padding: b,
        boxShadow: '0 50px 120px rgba(10,14,20,0.35), 0 12px 30px rgba(10,14,20,0.25), inset 0 0 0 2px #2A3038',
        transform: `rotate(${tilt}deg)`,
        ...style,
      }}
    >
      <div style={{position: 'relative', width: '100%', height: '100%', borderRadius: w * 0.13, overflow: 'hidden', background: screen}}>
        {children}
        <div
          style={{
            position: 'absolute',
            top: w * 0.03,
            left: '50%',
            width: w * 0.28,
            height: w * 0.075,
            marginLeft: -w * 0.14,
            borderRadius: 99,
            background: '#05070A',
          }}
        />
      </div>
    </div>
  );
};

export const CountUp: React.FC<{from: number; to: number; a: number; b: number; fmt?: (v: number) => string; style?: Pos}> = ({
  from,
  to,
  a,
  b,
  fmt = (v) => Math.round(v).toString(),
  style,
}) => {
  const {t} = useScene();
  const v = mix(from, to, ramp(t, a, b));
  return <span style={{fontVariantNumeric: 'tabular-nums', ...style}}>{fmt(v)}</span>;
};

/** Indian digit grouping: 4,80,000 */
export const inr = (v: number) => {
  const s = Math.round(v).toString();
  if (s.length <= 3) return s;
  const last = s.slice(-3);
  const rest = s.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  return `${rest},${last}`;
};

/** Speech bars: lively while `on`, flat otherwise. */
export const Waveform: React.FC<{bars?: number; w?: number; h?: number; color?: string; on?: number}> = ({bars = 48, w = 520, h = 120, color = C.brand, on = 1}) => {
  const {t} = useScene();
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: w / bars / 3, width: w, height: h}}>
      {Array.from({length: bars}).map((_, i) => {
        const n = Math.abs(Math.sin(t * 7.1 + i * 0.7) * Math.sin(t * 3.3 + i * 1.9) + 0.35 * Math.sin(t * 11 + i * 0.3));
        const hh = Math.max(0.06, n * on) * h;
        return <div key={i} style={{flex: 1, height: hh, borderRadius: 99, background: color, opacity: 0.35 + 0.65 * n}} />;
      })}
    </div>
  );
};

/** The Countersign mark: blue rounded square, a white wave drawn on (web/public/icon.svg). */
export const Logo: React.FC<{size?: number; draw?: number}> = ({size = 160, draw = 1}) => (
  <svg width={size} height={size} viewBox="0 0 64 64">
    <rect width="64" height="64" rx="14" fill={C.brand} />
    <path
      d="M12 40c4-14 8-14 10 0s6 14 10 0 6-14 10 0 6 6 10-4"
      fill="none"
      stroke="#fff"
      strokeWidth="4"
      strokeLinecap="round"
      pathLength={1}
      strokeDasharray={1}
      strokeDashoffset={1 - draw}
    />
  </svg>
);

/** Full-frame background with a soft light, and film grain so flat colour doesn't band. */
export const Bg: React.FC<{dark?: boolean}> = ({dark}) => (
  <AbsoluteFill
    style={{
      background: dark
        ? `radial-gradient(1200px 800px at 50% 40%, ${C.night2} 0%, ${C.night} 70%)`
        : `radial-gradient(1400px 900px at 50% 35%, #FFFFFF 0%, ${C.paper} 75%)`,
    }}
  >
    <Grain opacity={dark ? 0.07 : 0.045} />
  </AbsoluteFill>
);

const Grain: React.FC<{opacity: number}> = ({opacity}) => (
  <svg width="100%" height="100%" style={{position: 'absolute', inset: 0, opacity, mixBlendMode: 'overlay'}}>
    <filter id="grain">
      <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" />
    </filter>
    <rect width="100%" height="100%" filter="url(#grain)" />
  </svg>
);

/** Small print, bottom left (the reference's "Sample school. Illustrative data."). */
export const SmallPrint: React.FC<{text: string; dark?: boolean; at?: number}> = ({text, dark, at = 0.2}) => {
  const {t} = useScene();
  return (
    <div
      style={{
        position: 'absolute',
        left: 64,
        bottom: 44,
        fontFamily: FONT,
        fontSize: 20,
        fontWeight: 500,
        color: dark ? C.nightMuted : C.muted,
        opacity: ramp(t, at, at + 0.6) * 0.9,
      }}
    >
      {text}
    </div>
  );
};

/** Top-left wordmark for the light act. */
export const Brand: React.FC = () => (
  <div style={{position: 'absolute', left: 64, top: 48, display: 'flex', alignItems: 'center', gap: 14, fontFamily: FONT, fontWeight: 650, fontSize: 26, color: C.ink, letterSpacing: '-0.02em'}}>
    <Logo size={34} />
    Countersign
  </div>
);

/** "Real app, recorded" tag for clips from the emulator. */
export const RealTag: React.FC<{style?: Pos}> = ({style}) => (
  <div
    style={{
      position: 'absolute',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '10px 18px',
      borderRadius: 99,
      background: C.ink,
      color: C.white,
      fontFamily: FONT,
      fontWeight: 600,
      fontSize: 22,
      ...style,
    }}
  >
    <span style={{width: 12, height: 12, borderRadius: 99, background: '#E5484D'}} />
    Real app, recorded
  </div>
);

/** A sound effect at `at` seconds into the scene. */
export const Sfx: React.FC<{name: string; at: number; volume?: number}> = ({name, at, volume = 0.6}) => {
  const {fps} = useVideoConfig();
  return (
    <Sequence from={Math.round(at * fps)} layout="none">
      <Audio src={staticFile(`audio/sfx_${name}.wav`)} volume={volume} />
    </Sequence>
  );
};
