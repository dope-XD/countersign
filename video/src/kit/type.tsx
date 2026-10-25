import React from 'react';
import {C, FONT, HINDI} from '../theme';
import {ramp, useScene} from './time';

const seg = new Intl.Segmenter('hi', {granularity: 'grapheme'});

/** Text typed out grapheme by grapheme (so Devanagari never shows a broken letter), with a caret while typing. */
export const Typed: React.FC<{text: string; at: number; cps?: number; style?: React.CSSProperties; caret?: string}> = ({text, at, cps = 22, style, caret = C.brand}) => {
  const {t} = useScene();
  const g = Array.from(seg.segment(text), (s) => s.segment);
  const n = Math.max(0, Math.min(g.length, Math.floor((t - at) * cps)));
  const typing = n > 0 && n < g.length;
  if (t < at) return null;
  return (
    <span style={style}>
      {g.slice(0, n).join('')}
      {typing && <span style={{display: 'inline-block', width: 3, height: '1em', background: caret, marginLeft: 3, verticalAlign: '-0.12em'}} />}
    </span>
  );
};

/** A caller's line: Hindi typed out, the English below. */
export const Said: React.FC<{hi: string; en: string; at: number; dark?: boolean; style?: React.CSSProperties}> = ({hi, en, at, dark = true, style}) => {
  const {t} = useScene();
  const p = ramp(t, at, at + 0.5);
  const enAt = at + Array.from(seg.segment(hi)).length / 22 + 0.1;
  return (
    <div style={{opacity: p, transform: `translateY(${(1 - p) * 30}px)`, ...style}}>
      <div
        style={{
          display: 'inline-block',
          background: dark ? C.nightCard : C.white,
          border: `1px solid ${dark ? C.nightLine : C.line}`,
          borderRadius: '28px 28px 28px 8px',
          padding: '22px 30px',
          boxShadow: '0 20px 50px rgba(0,0,0,0.3)',
          whiteSpace: 'nowrap',
        }}
      >
        <div style={{fontFamily: HINDI, fontSize: 46, fontWeight: 600, color: dark ? C.nightText : C.ink, lineHeight: 1.35, minHeight: 62}}>
          <Typed text={hi} at={at} />
        </div>
        <div style={{fontFamily: FONT, fontSize: 24, color: dark ? C.nightMuted : C.muted, marginTop: 4, opacity: ramp(t, enAt, enAt + 0.4)}}>{en}</div>
      </div>
    </div>
  );
};
