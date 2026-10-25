// The cut to light: the logo, and the family it protects.
import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Bg, Logo, Sfx, Words} from '../kit/motion';
import {EASE_IO, mix, ramp, useScene} from '../kit/time';
import {C, FONT} from '../theme';

export const FAMILY = [
  {name: 'Mummy', color: '#B3261E'},
  {name: 'Papa', color: '#0B5CAD'},
  {name: 'Rahul', color: '#137A3F'},
  {name: 'Priya', color: '#9A5B00'},
];

export const Face: React.FC<{name: string; color: string; size?: number; label?: boolean}> = ({name, color, size = 120, label = true}) => (
  <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, fontFamily: FONT}}>
    <div
      style={{
        width: size,
        height: size,
        borderRadius: 999,
        background: '#fff',
        border: `${size * 0.04}px solid ${color}`,
        display: 'grid',
        placeItems: 'center',
        color,
        fontWeight: 750,
        fontSize: size * 0.42,
        boxShadow: '0 14px 34px rgba(20,32,43,0.12)',
      }}
    >
      {name[0]}
    </div>
    {label && <div style={{fontSize: size * 0.22, fontWeight: 600, color: C.ink}}>{name}</div>}
  </div>
);

export const S04: React.FC = () => {
  const {t, cue, out} = useScene();
  const open = ramp(t, 0, 0.7, EASE_IO);
  const draw = ramp(t, 0.35, 1.4, EASE_IO);
  const name = cue('Countersign');
  const fam = cue('Everyone in the family');
  const lift = ramp(t, fam - 0.3, fam + 0.4, EASE_IO);
  const q = ramp(t, out, out + 0.45);
  return (
    <AbsoluteFill>
      <Bg dark />
      <AbsoluteFill style={{clipPath: `circle(${open * 75}% at 50% 50%)`}}>
        <Bg />
        <div style={{position: 'absolute', left: 0, right: 0, top: mix(390, 250, lift), display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 40, opacity: 1 - q, filter: q > 0 ? `blur(${q * 12}px)` : undefined}}>
          <div style={{transform: `scale(${mix(0.6, 1, ramp(t, 0.2, 0.9))}) rotate(${mix(-8, 0, ramp(t, 0.2, 1))}deg)`}}>
            <Logo size={190} draw={draw} />
          </div>
          <Words text="Countersign" at={name} size={150} weight={700} />
        </div>
        <div style={{position: 'absolute', left: 0, right: 0, top: 520, display: 'flex', justifyContent: 'center'}}>
          <Words text="For the whole family." at={fam} size={60} weight={550} color={C.muted} out={out} />
        </div>
        <div style={{position: 'absolute', left: 0, right: 0, top: 660, display: 'flex', justifyContent: 'center', gap: 110}}>
          {FAMILY.map((f, i) => {
            const p = ramp(t, fam + 0.25 + i * 0.1, fam + 0.85 + i * 0.1);
            const e = ramp(t, out, out + 0.45);
            return (
              <div key={f.name} style={{opacity: p * (1 - e), transform: `translateY(${(1 - p) * 50}px) scale(${mix(0.7, 1, p)})`, filter: e > 0 ? `blur(${e * 12}px)` : undefined}}>
                <Face {...f} />
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
      <Sfx name="impact" at={0} volume={0.7} />
      <Sfx name="pop" at={fam + 0.25} volume={0.35} />
    </AbsoluteFill>
  );
};
