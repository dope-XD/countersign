// How it works (the pipeline, then the red alarm), in the app's light colours.
import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Bg, Brand, Card, Chip, Phone, Pop, Sfx, Underline, Waveform, Words} from '../kit/motion';
import {AppButton, FamilyAlarm, InCall, PayGuard, PayScreen, RiskCard, SmsBubble} from '../kit/screens';
import {EASE_IO, mix, ramp, useScene} from '../kit/time';
import {Typed} from '../kit/type';
import {C, FONT, HINDI} from '../theme';
import {Face} from './S04';

const clock = (t: number, base = 754) => {
  const s = Math.floor(base + t);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};

const Label: React.FC<{n: string; text: string}> = ({n, text}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 14, fontFamily: FONT, fontSize: 24, fontWeight: 650, color: C.muted, marginBottom: 16}}>
    <span style={{width: 34, height: 34, borderRadius: 99, background: C.brand, color: '#fff', display: 'grid', placeItems: 'center', fontSize: 19}}>{n}</span>
    {text}
  </div>
);

/** The meter: how far the call has gone towards a scam, with the app's three levels. */
const Meter: React.FC<{p: number}> = ({p}) => {
  const fill = p < 0.33 ? C.green : p < 0.8 ? C.amberBright : C.red;
  return (
    <div style={{fontFamily: FONT}}>
      <div style={{position: 'relative', height: 26, borderRadius: 99, background: C.greySoft, overflow: 'hidden'}}>
        <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: `${p * 100}%`, background: fill, borderRadius: 99}} />
      </div>
      <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 20, color: C.muted, marginTop: 10, fontWeight: 600}}>
        <span>Fine</span>
        <span style={{color: p >= 0.33 ? C.amber : undefined}}>Amber</span>
        <span style={{color: p >= 0.8 ? C.red : undefined}}>Red</span>
      </div>
    </div>
  );
};

export const S05: React.FC = () => {
  const {t, cue, out} = useScene();
  const hear = cue('On speaker');
  const model = cue('A model we trained');
  const ask = cue('is this caller doing');
  const police = cue("Saying he's police");
  const quiet = cue('Telling her to keep quiet');
  const amber = cue('The card turns amber');
  const rahul = cue('If the caller claims to be Rahul');
  const no = cue('It says no');
  const p = mix(0.04, 0.22, ramp(t, model, police)) + 0.14 * ramp(t, police, police + 0.6) + 0.12 * ramp(t, quiet, quiet + 0.6);
  const dim = ramp(t, amber - 0.2, amber + 0.4);
  const gone = ramp(t, rahul - 0.1, rahul + 0.4);
  const phoneX = mix(150, 330, ramp(t, rahul - 0.1, rahul + 0.6, EASE_IO));
  return (
    <AbsoluteFill>
      <Bg />
      <Brand />
      {/* Mummy's phone, on speaker */}
      <Pop at={0} out={out} from="left" style={{left: 0, top: 0}}>
        <div style={{position: 'absolute', left: phoneX + 100, top: 120}}>
          <Face name="Mummy" color={C.red} size={56} label={false} />
        </div>
        <Phone w={400} screen="#0E1217" style={{left: phoneX, top: 200}}>
          <InCall name="Unknown number" time={clock(t)}>
            {t < amber ? (
              <RiskCard tone="listen" headline="Listening for scams" body="Checked on this phone." />
            ) : (
              <RiskCard
                tone="amber"
                headline="This sounds like a “digital arrest” scam."
                body="Police never ask for money on a call."
                why="Why: says police, court or bank · asks you to keep it secret"
                style={{transform: `scale(${mix(0.92, 1, ramp(t, amber, amber + 0.4))})`}}
              >
                {t > no ? (
                  <div style={{display: 'flex', flexDirection: 'column', gap: 6}}>
                    <div style={{background: C.redSoft, color: C.red, borderRadius: 99, padding: '8px 14px', fontSize: 17, fontWeight: 700, alignSelf: 'flex-start'}}>Not Rahul's phone</div>
                    <div style={{fontSize: 16, color: C.ink}}>Rahul's phone isn't on a call.</div>
                  </div>
                ) : (
                  <AppButton text="Alert family" kind="no" />
                )}
              </RiskCard>
            )}
          </InCall>
        </Phone>
      </Pop>
      {/* the pipeline */}
      <div style={{position: 'absolute', left: 700, top: 150, width: 1100, opacity: (1 - dim) * (1 - gone), filter: dim > 0 ? `blur(${dim * 10}px)` : undefined}}>
        <Pop at={hear} from="right" style={{left: 0, top: 0, width: 1100}}>
          <Label n="1" text="Speech to text, on the phone" />
          <Card style={{display: 'flex', gap: 34, alignItems: 'center', padding: '24px 34px'}}>
            <Waveform bars={26} w={200} h={90} on={t < amber ? 1 : 0.2} />
            <div style={{fontFamily: HINDI, fontSize: 32, fontWeight: 600, lineHeight: 1.45, color: C.ink, whiteSpace: 'nowrap'}}>
              <div><Typed text="मैं CBI से बोल रहा हूँ..." at={hear + 0.3} cps={30} /></div>
              <div><Typed text="आपके नाम पे पार्सल मिला है।" at={model - 0.4} cps={30} /></div>
              <div><Typed text="किसी को मत बताना।" at={police - 0.2} cps={30} /></div>
            </div>
          </Card>
        </Pop>
        <Pop at={model} from="right" style={{left: 0, top: 330, width: 1100}}>
          <Label n="2" text="Our model reads the whole call so far" />
          <Card style={{padding: '28px 34px'}}>
            <div style={{fontFamily: FONT, fontSize: 34, fontWeight: 650, color: C.ink, marginBottom: 22, opacity: ramp(t, ask, ask + 0.4), letterSpacing: '-0.02em'}}>
              Is this caller doing what scammers do?
            </div>
            <Meter p={p} />
          </Card>
        </Pop>
        <div style={{position: 'absolute', left: 0, top: 680, display: 'flex', gap: 22}}>
          <Pop at={police} from="up" style={{position: 'relative'}}>
            <Chip text="Says he's police" fg={C.amber} bg={C.amberSoft} size={30} />
          </Pop>
          <Pop at={quiet} from="up" style={{position: 'relative'}}>
            <Chip text="Tells her to keep quiet" fg={C.amber} bg={C.amberSoft} size={30} />
          </Pop>
        </div>
      </div>
      {/* amber: the why */}
      <div style={{position: 'absolute', left: 720, top: 470, opacity: 1 - gone, filter: gone > 0 ? `blur(${gone * 10}px)` : undefined}}>
        <div style={{position: 'relative'}}>
          <Words text="It says why, in plain words." at={amber + 0.2} size={92} weight={700} />
          <Underline at={amber + 0.7} color={C.amberBright} />
        </div>
      </div>
      {/* the Rahul check */}
      <Pop at={rahul} out={out} from="right" dist={160} style={{left: 1300, top: 0}}>
        <div style={{position: 'absolute', left: 140, top: 120}}>
          <Face name="Rahul" color={C.green} size={56} label={false} />
        </div>
        <Phone w={340} screen="#151A22" style={{left: 0, top: 200}}>
          <div style={{position: 'absolute', top: 120, left: 0, right: 0, textAlign: 'center', color: '#fff', fontFamily: FONT, fontSize: 64, fontWeight: 300}}>12:58</div>
          <div style={{position: 'absolute', top: 210, left: 0, right: 0, textAlign: 'center', color: '#9AA6B3', fontFamily: FONT, fontSize: 20}}>Rahul's phone, in his pocket</div>
        </Phone>
        <div style={{position: 'absolute', left: 30, top: 940, opacity: ramp(t, no, no + 0.3)}}>
          <Chip text="Not on a call" fg={C.red} bg={C.redSoft} size={28} />
        </div>
      </Pop>
      <Arc t={t} a={rahul + 0.4} b={no} out={out} />
      <Sfx name="whoosh" at={hear} volume={0.3} />
      <Sfx name="whoosh" at={model} volume={0.3} />
      <Sfx name="pop" at={police} volume={0.35} />
      <Sfx name="pop" at={quiet} volume={0.35} />
      <Sfx name="amber" at={amber} volume={0.55} />
      <Sfx name="whoosh" at={rahul} volume={0.35} />
      <Sfx name="tick" at={no} volume={0.4} />
    </AbsoluteFill>
  );
};

/** A dotted arc between the two phones, with a dot travelling along it. */
const Arc: React.FC<{t: number; a: number; b: number; out: number}> = ({t, a, b, out}) => {
  const p = ramp(t, a, a + 0.5);
  const q = ramp(t, out, out + 0.4);
  const d = ((t - a) % 1.1) / 1.1;
  const path = 'M 760 300 Q 1040 120 1330 300';
  return (
    <svg width={1920} height={1080} style={{position: 'absolute', inset: 0, opacity: p * (1 - q)}}>
      <path d={path} fill="none" stroke={C.brand} strokeWidth={4} strokeDasharray="4 14" strokeLinecap="round" />
      {t > a && t < b + 0.3 && <circle cx={mix(760, 1330, d)} cy={300 - Math.sin(d * Math.PI) * 90} r={11} fill={C.brand} />}
      <text x={1045} y={170} textAnchor="middle" fontFamily={FONT} fontSize={26} fontWeight={650} fill={C.ink}>
        Are you on this call?
      </text>
    </svg>
  );
};

export const S06: React.FC = () => {
  const {t, cue, out} = useScene();
  const red = cue('If it turns red');
  const ring = cue("Rahul's phone rings");
  const sms = cue('or he gets an SMS');
  const pay = cue('If Mummy opens GPay');
  const guard = cue('a red screen gets there first');
  const flash = ramp(t, red, red + 0.15) * (1 - ramp(t, red + 0.15, red + 0.9));
  const focus = ramp(t, pay - 0.4, pay + 0.4, EASE_IO);
  const pulse = (1 + Math.sin(t * 9)) / 2;
  const mummyX = mix(200, 560, focus);
  return (
    <AbsoluteFill>
      <Bg />
      <AbsoluteFill style={{background: C.red, opacity: flash * 0.18}} />
      <Brand />
      {/* Mummy */}
      <Pop at={0} out={out} from="none" style={{left: 0, top: 0}}>
        <div style={{position: 'absolute', left: mummyX + 92, top: 110}}>
          <Face name="Mummy" color={C.red} size={56} label={false} />
        </div>
        <Phone w={380} screen="#0E1217" style={{left: mummyX, top: 190}}>
          <InCall name="Unknown number" time={clock(t, 790)}>
            <RiskCard tone="red" headline="This is likely a scam. Hang up." why="Why: says police, court or bank · asks you to keep it secret">
              <div style={{fontSize: 17, color: C.ink, fontWeight: 600}}>Family alerted</div>
            </RiskCard>
          </InCall>
          {t > pay && (
            <div style={{position: 'absolute', inset: 0}}>
              <PayScreen to="Account 4471" amount="2,00,000" />
            </div>
          )}
          {t > guard - 0.1 && (
            <div style={{position: 'absolute', inset: 0, transform: `translateY(${(1 - ramp(t, guard - 0.1, guard + 0.35)) * 100}%)`}}>
              <PayGuard who="Rahul" app="GPay" />
            </div>
          )}
        </Phone>
      </Pop>
      {/* Rahul: the family alarm */}
      <div style={{position: 'absolute', inset: 0, opacity: 1 - focus, filter: focus > 0 ? `blur(${focus * 12}px)` : undefined, transform: `translateX(${focus * 200}px)`}}>
        <Pop at={ring} from="up" dist={100} style={{left: 760, top: 0}}>
          <div style={{position: 'absolute', left: 92, top: 110}}>
            <Face name="Rahul" color={C.green} size={56} label={false} />
          </div>
          <div style={{position: 'absolute', left: 190 - 260, top: 600 - 260, width: 520, height: 520, borderRadius: 999, background: C.red, opacity: 0.08 + pulse * 0.08, transform: `scale(${1 + pulse * 0.1})`}} />
          <Phone w={380} screen={C.redSoft} style={{left: 0, top: 190, transform: `rotate(${Math.sin(t * 50) * 0.8 * (t < ring + 2 ? 1 : 0)}deg)`}}>
            <FamilyAlarm who="Mummy" line="It sounds like a “digital arrest” scam." />
          </Phone>
        </Pop>
        <Pop at={sms} from="up" dist={100} style={{left: 1300, top: 0}}>
          <div style={{position: 'absolute', left: 92, top: 110}}>
            <Face name="Papa" color={C.brand} size={56} label={false} />
          </div>
          <Phone w={380} screen="#151A22" style={{left: 0, top: 190}}>
            <div style={{position: 'absolute', top: 120, left: 0, right: 0, textAlign: 'center', color: '#fff', fontFamily: FONT, fontSize: 70, fontWeight: 300}}>12:59</div>
            <SmsBubble
              from="CS Bank"
              text="Mummy may be on a scam call right now. Please call them and tell them to cut the call."
              style={{position: 'absolute', top: 260, left: 14, width: 'auto', right: 14, transform: `translateY(${(1 - ramp(t, sms + 0.2, sms + 0.7)) * -40}px)`, opacity: ramp(t, sms + 0.2, sms + 0.7)}}
            />
          </Phone>
        </Pop>
      </div>
      <div style={{position: 'absolute', left: 1080, top: 430}}>
        <Words text="Before she pays." at={guard + 0.2} size={96} weight={700} out={out} />
      </div>
      <Sfx name="alarm" at={red} volume={0.5} />
      <Sfx name="ring" at={ring} volume={0.35} />
      <Sfx name="pop" at={sms + 0.2} volume={0.35} />
      <Sfx name="whoosh" at={guard - 0.1} volume={0.45} />
    </AbsoluteFill>
  );
};
