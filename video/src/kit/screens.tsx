// The app's screens, redrawn for the video with the app's own words (res/values/strings.xml) and colours.
import React from 'react';
import {C, FONT} from '../theme';

const col = (gap: number, extra?: React.CSSProperties): React.CSSProperties => ({display: 'flex', flexDirection: 'column', gap, ...extra});

/** Incoming call, dark dialer. */
export const IncomingCall: React.FC<{name: string; number: string; sub?: string}> = ({name, number, sub}) => (
  <div style={{...col(10, {alignItems: 'center'}), position: 'absolute', inset: 0, paddingTop: 150, background: 'linear-gradient(180deg,#1B222C 0%,#0E1217 100%)', fontFamily: FONT, color: '#fff'}}>
    <div style={{width: 110, height: 110, borderRadius: 99, background: '#2B3440', display: 'grid', placeItems: 'center', fontSize: 52, color: '#9AA6B3'}}>?</div>
    <div style={{fontSize: 34, fontWeight: 650, marginTop: 18, letterSpacing: '-0.02em'}}>{name}</div>
    <div style={{fontSize: 22, color: '#9AA6B3', fontVariantNumeric: 'tabular-nums'}}>{number}</div>
    {sub && <div style={{fontSize: 20, color: '#9AA6B3'}}>{sub}</div>}
    <div style={{position: 'absolute', bottom: 110, left: 0, right: 0, display: 'flex', justifyContent: 'space-around'}}>
      <Btn color="#E5484D" glyph="✕" />
      <Btn color="#30A46C" glyph="✆" />
    </div>
  </div>
);

const Btn: React.FC<{color: string; glyph: string}> = ({color, glyph}) => (
  <div style={{width: 84, height: 84, borderRadius: 99, background: color, display: 'grid', placeItems: 'center', fontSize: 36, color: '#fff'}}>{glyph}</div>
);

/** In a call, on speaker, with the app's card on top (the overlay). */
export const InCall: React.FC<{name: string; time: string; children?: React.ReactNode}> = ({name, time, children}) => (
  <div style={{position: 'absolute', inset: 0, background: 'linear-gradient(180deg,#1B222C 0%,#0E1217 100%)', fontFamily: FONT, color: '#fff'}}>
    <div style={{...col(6, {alignItems: 'center'}), paddingTop: 70}}>
      <div style={{fontSize: 28, fontWeight: 650}}>{name}</div>
      <div style={{fontSize: 20, color: '#9AA6B3', fontVariantNumeric: 'tabular-nums'}}>{time}</div>
    </div>
    <div style={{position: 'absolute', bottom: 70, left: 0, right: 0, display: 'flex', justifyContent: 'center', gap: 26}}>
      <Round label="Speaker" on />
      <Round label="Mute" />
      <Round label="End" red />
    </div>
    <div style={{position: 'absolute', left: 12, right: 12, top: 150}}>{children}</div>
  </div>
);

const Round: React.FC<{label: string; on?: boolean; red?: boolean}> = ({label, on, red}) => (
  <div style={{...col(8, {alignItems: 'center'}), fontSize: 15, color: '#9AA6B3'}}>
    <div style={{width: 62, height: 62, borderRadius: 99, background: red ? '#E5484D' : on ? '#fff' : '#2B3440'}} />
    {label}
  </div>
);

/** RiskCard from overlay/CallCheckCard.kt: coloured soft card, headline, advice and why, then actions. */
export const RiskCard: React.FC<{
  tone: 'amber' | 'red' | 'grey' | 'green' | 'listen';
  headline: string;
  body?: string;
  why?: string;
  children?: React.ReactNode;
  style?: React.CSSProperties;
}> = ({tone, headline, body, why, children, style}) => {
  const bg = {amber: C.amberSoft, red: C.redSoft, grey: C.greySoft, green: C.greenSoft, listen: C.white}[tone];
  const fg = {amber: C.amber, red: C.red, grey: C.grey, green: C.green, listen: C.brand}[tone];
  const warn = tone === 'amber' || tone === 'red' || tone === 'grey';
  return (
    <div style={{background: C.white, borderRadius: 24, padding: 10, boxShadow: '0 20px 50px rgba(0,0,0,0.35)', fontFamily: FONT, ...style}}>
      <div style={{background: bg, borderRadius: 18, padding: '14px 16px', border: `3px solid ${fg}`, ...col(8)}}>
        <div style={{display: 'flex', gap: 10, alignItems: 'flex-start'}}>
          {warn && (
            <svg width={26} height={26} viewBox="0 0 24 24" style={{flexShrink: 0, marginTop: 1}}>
              <path d="M12 2 1 21h22L12 2z" fill={tone === 'grey' ? C.grey : fg} />
              <rect x="11" y="9" width="2" height="6" fill={bg} />
              <rect x="11" y="16.5" width="2" height="2" fill={bg} />
            </svg>
          )}
          <div style={{fontSize: 21, fontWeight: 700, lineHeight: 1.25, color: tone === 'red' ? C.red : C.ink}}>{headline}</div>
        </div>
        {body && <div style={{fontSize: 17, lineHeight: 1.35, color: C.ink}}>{body}</div>}
        {why && <div style={{fontSize: 17, lineHeight: 1.35, color: C.ink}}>{why}</div>}
        {children}
      </div>
    </div>
  );
};

export const AppButton: React.FC<{text: string; kind?: 'no' | 'yes' | 'quiet' | 'white'; style?: React.CSSProperties}> = ({text, kind = 'no', style}) => {
  const s = {
    no: {background: C.red, color: '#fff'},
    yes: {background: C.green, color: '#fff'},
    quiet: {background: 'transparent', color: C.ink, border: `2px solid ${C.line}`},
    white: {background: '#fff', color: C.guardRed},
  }[kind];
  return (
    <div style={{borderRadius: 14, padding: '13px 18px', fontSize: 18, fontWeight: 650, textAlign: 'center', fontFamily: FONT, ...s, ...style}}>{text}</div>
  );
};

/** FamilyAlarm.kt: full screen on a family member's phone. */
export const FamilyAlarm: React.FC<{who: string; line: string; cleared?: boolean}> = ({who, line, cleared}) => (
  <div style={{position: 'absolute', inset: 0, background: cleared ? C.greenSoft : C.redSoft, fontFamily: FONT, padding: '90px 26px 30px', ...col(18)}}>
    <div style={{width: 76, height: 76, borderRadius: 99, background: cleared ? C.green : C.red, display: 'grid', placeItems: 'center', color: '#fff', fontSize: 44, fontWeight: 800}}>
      {cleared ? '✓' : '!'}
    </div>
    <div style={{fontSize: 33, fontWeight: 750, lineHeight: 1.15, color: cleared ? C.green : C.red, letterSpacing: '-0.02em'}}>
      {cleared ? `False alarm: ${who} says it's fine` : `${who} may be on a scam call`}
    </div>
    <div style={{fontSize: 19, lineHeight: 1.35, color: C.ink}}>{line}</div>
    <div style={{fontSize: 17, color: C.muted}}>Just now</div>
    <div style={{flex: 1}} />
    {!cleared && (
      <>
        <AppButton text={`Call ${who}`} kind="yes" />
        <AppButton text={`Message ${who}`} kind="quiet" />
      </>
    )}
  </div>
);

/** PayGuardScreen.kt: red, over a payment app. */
export const PayGuard: React.FC<{who: string; app: string}> = ({who, app}) => (
  <div style={{position: 'absolute', inset: 0, background: C.guardRed, fontFamily: FONT, color: '#fff', padding: '100px 26px 30px', ...col(16)}}>
    <div style={{fontSize: 64, lineHeight: 1}}>⚠</div>
    <div style={{fontSize: 34, fontWeight: 750, lineHeight: 1.15, letterSpacing: '-0.02em'}}>Stop. This caller isn't {who}.</div>
    <div style={{fontSize: 19, lineHeight: 1.35}}>Don't send money in {app} or share an OTP.</div>
    <div style={{flex: 1}} />
    <AppButton text={`Ring ${who}`} kind="white" />
    <AppButton text={`Call ${who}`} kind="quiet" style={{color: '#fff', borderColor: '#fff'}} />
    <AppButton text="I understand" kind="quiet" style={{color: '#fff', borderColor: '#fff'}} />
  </div>
);

/** A generic payment screen (no real app's branding). */
export const PayScreen: React.FC<{amount: string; to: string; sent?: number}> = ({amount, to, sent = 0}) => (
  <div style={{position: 'absolute', inset: 0, background: '#fff', fontFamily: FONT, padding: '90px 28px 30px', ...col(14)}}>
    <div style={{fontSize: 18, color: C.muted}}>Paying</div>
    <div style={{fontSize: 24, fontWeight: 650, color: C.ink}}>{to}</div>
    <div style={{fontSize: 58, fontWeight: 750, color: C.ink, letterSpacing: '-0.03em', marginTop: 30, fontVariantNumeric: 'tabular-nums'}}>₹{amount}</div>
    <div style={{flex: 1}} />
    <div
      style={{
        borderRadius: 16,
        padding: 18,
        textAlign: 'center',
        fontSize: 22,
        fontWeight: 700,
        color: '#fff',
        background: sent > 0.5 ? C.ink : C.brand,
      }}
    >
      {sent > 0.5 ? 'Sent ✓' : 'Pay'}
    </div>
  </div>
);

export const SmsBubble: React.FC<{from: string; text: string; style?: React.CSSProperties}> = ({from, text, style}) => (
  <div style={{background: '#fff', borderRadius: 22, padding: '16px 20px', boxShadow: '0 20px 50px rgba(20,32,43,0.14)', fontFamily: FONT, width: 400, ...col(6), ...style}}>
    <div style={{fontSize: 16, fontWeight: 650, color: C.muted}}>SMS · {from}</div>
    <div style={{fontSize: 19, lineHeight: 1.35, color: C.ink}}>{text}</div>
  </div>
);
