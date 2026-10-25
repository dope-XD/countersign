// What it still misses, the way out of a false alarm, what's kept, and the end card.
import React from 'react';
import {AbsoluteFill, OffthreadVideo, Sequence, getStaticFiles, staticFile, useVideoConfig} from 'remotion';
import {Bg, Brand, Card, Logo, Phone, Pop, RealTag, Sfx, Underline, Waveform, Words} from '../kit/motion';
import {AppButton, FamilyAlarm, InCall, RiskCard} from '../kit/screens';
import {EASE_IO, mix, ramp, useScene} from '../kit/time';
import {C, FONT} from '../theme';
import {Face} from './S04';

const Miss: React.FC<{title: string; quote: string; result: string; tone: 'grey' | 'amber'; verdict: string}> = ({title, quote, result, tone, verdict}) => (
  <Card style={{width: 780, padding: 44}}>
    <div style={{fontSize: 26, color: C.muted, fontWeight: 650}}>{title}</div>
    <div style={{fontSize: 36, lineHeight: 1.4, fontWeight: 500, marginTop: 16, color: C.ink}}>{quote}</div>
    <div style={{display: 'flex', alignItems: 'center', gap: 18, marginTop: 28}}>
      <div style={{background: tone === 'grey' ? C.greySoft : C.amberSoft, color: tone === 'grey' ? C.grey : C.amber, fontWeight: 700, fontSize: 26, borderRadius: 99, padding: '10px 22px'}}>{result}</div>
      <div style={{fontSize: 26, fontWeight: 700, color: C.red}}>{verdict}</div>
    </div>
  </Card>
);

/** A finger tap: a ring that grows and fades. */
const Tap: React.FC<{x: number; y: number; at: number}> = ({x, y, at}) => {
  const {t} = useScene();
  const p = ramp(t, at - 0.15, at + 0.45);
  if (p <= 0 || p >= 1) return null;
  return (
    <div style={{position: 'absolute', left: x - 40, top: y - 40, width: 80, height: 80, borderRadius: 99, background: 'rgba(20,32,43,0.25)', border: '3px solid rgba(20,32,43,0.5)', opacity: 1 - p, transform: `scale(${mix(0.5, 1.6, p)})`}} />
  );
};

export const S09: React.FC = () => {
  const {t, cue, out} = useScene();
  const {fps} = useVideoConfig();
  const head = Math.min(cue("It isn't perfect"), 0.25);
  const polite = cue('A scam read politely');
  const rel = cue('and relatives talking');
  const wrong = cue("If it's wrong");
  const tap1 = cue('two taps');
  const yes = tap1 + 1.45;
  const gone = cue('and tell the family');
  const server = cue('Only suspicious calls');
  const dropped = cue('and the audio is dropped');
  const keep = cue('We keep one thing');
  const missOut = ramp(t, wrong - 0.3, wrong + 0.1);
  const flowIn = ramp(t, server + 0.2, server + 0.6);
  const clip = getStaticFiles().find((f) => f.name === 'clips/not_a_scam.mp4');
  // the voice travels from the phone to the server, then is dropped
  const travel = ramp(t, server + 0.4, dropped, EASE_IO);
  const drop = ramp(t, dropped, dropped + 0.8);
  return (
    <AbsoluteFill>
      <Bg />
      <Brand />
      {/* what it still misses */}
      <div style={{position: 'absolute', inset: 0, opacity: 1 - missOut, filter: missOut > 0 ? `blur(${missOut * 12}px)` : undefined}}>
        <div style={{position: 'absolute', left: 140, top: 150}}>
          <Words text="What it still misses." at={head} size={80} weight={700} />
        </div>
        <Pop at={polite} from="up" style={{left: 140, top: 340}}>
          <Miss title="A polite scam, read from a script, in English" quote="“Good afternoon, ma'am. This is about a parcel booked in your name…”" result="Stays at watch" tone="grey" verdict="Missed" />
        </Pop>
        <Pop at={rel} from="up" style={{left: 1000, top: 340}}>
          <Miss title="Relatives talking about a scam" quote="“Did you hear? Sharma ji got one of those digital arrest calls.”" result="Turns amber" tone="amber" verdict="False alarm" />
        </Pop>
      </div>
      {/* the way out: two taps */}
      {t > wrong - 0.4 && t < server + 0.7 && (
        <div style={{position: 'absolute', inset: 0, opacity: 1 - flowIn, filter: flowIn > 0 ? `blur(${flowIn * 12}px)` : undefined}}>
          <div style={{position: 'absolute', left: 140, top: 150}}>
            <Words text="Wrong? Two taps." at={wrong - 0.1} size={80} weight={700} />
          </div>
          {clip ? (
            <Pop at={wrong - 0.1} from="up" style={{left: 845, top: 220}}>
              <div style={{width: 640, height: 664, borderRadius: 28, overflow: 'hidden', boxShadow: '0 40px 100px rgba(20,32,43,0.22)', border: `1px solid ${C.line}`, position: 'relative', background: '#fff'}}>
                <Sequence from={Math.round((tap1 - 1.02) * fps)} layout="none">
                  <OffthreadVideo src={staticFile('clips/not_a_scam.mp4')} muted style={{width: 640, height: 664, objectFit: 'cover'}} />
                </Sequence>
                <Tap x={227 * 0.8} y={458 * 0.8} at={tap1} />
                <Tap x={226 * 0.8} y={291 * 0.8} at={tap1 + 1.45} />
              </div>
              <RealTag style={{left: 0, top: 690}} />
            </Pop>
          ) : (
          <Pop at={wrong} from="up" style={{left: 880, top: 0}}>
            <div style={{position: 'absolute', left: 92, top: 110}}>
              <Face name="Mummy" color={C.red} size={56} label={false} />
            </div>
            <Phone w={380} screen="#0E1217" style={{left: 0, top: 190}}>
                <InCall name="Sharma ji" time="03:12">
                  {t < tap1 + 0.2 ? (
                    <RiskCard tone="red" headline="This is likely a scam. Hang up." why="Why: says police, court or bank">
                      <div style={{fontSize: 17, color: C.ink, textDecoration: 'underline', fontWeight: 600}}>It's not a scam</div>
                    </RiskCard>
                  ) : t < yes + 0.2 ? (
                    <RiskCard tone="grey" headline="Is this call fine?" body="We'll stop warning and tell your family it's fine.">
                      <div style={{display: 'flex', gap: 10}}>
                        <AppButton text="Yes, it's fine" kind="yes" style={{flex: 1.3}} />
                        <AppButton text="Back" kind="quiet" style={{flex: 1, background: '#fff'}} />
                      </div>
                    </RiskCard>
                  ) : (
                    <RiskCard tone="green" headline="Cleared. Family told it's fine." />
                  )}
                </InCall>
            </Phone>
            <Tap x={110} y={190 + 312} at={tap1} />
            <Tap x={110} y={190 + 330} at={yes} />
          </Pop>
          )}
          <Pop at={gone} from="right" style={{left: 1510, top: 0}}>
            <div style={{position: 'absolute', left: 92, top: 110}}>
              <Face name="Rahul" color={C.green} size={56} label={false} />
            </div>
            <Phone w={380} screen={C.greenSoft} style={{left: 0, top: 190}}>
              <FamilyAlarm who="Mummy" line="Mummy told the app it's not a scam. You don't need to do anything." cleared />
            </Phone>
          </Pop>
        </div>
      )}
      {/* privacy: what reaches the server, and what is kept */}
      {t > server + 0.2 && (
        <AbsoluteFill style={{opacity: flowIn}}>
          <div style={{position: 'absolute', left: 140, top: 150}}>
            <Words text="What happens to the audio." at={server} size={80} weight={700} out={out} />
          </div>
          <Pop at={server} out={out} from="left" style={{left: 140, top: 360}}>
            <Card style={{width: 520, padding: 40}}>
              <div style={{fontSize: 24, color: C.muted, fontWeight: 650}}>Mummy's phone</div>
              <div style={{fontSize: 38, fontWeight: 750, marginTop: 8, letterSpacing: '-0.02em'}}>Checks every call itself</div>
            </Card>
          </Pop>
          <Pop at={server + 0.2} out={out} from="right" style={{left: 1260, top: 360}}>
            <Card style={{width: 520, padding: 40}}>
              <div style={{fontSize: 24, color: C.muted, fontWeight: 650}}>Our server</div>
              <div style={{fontSize: 38, fontWeight: 750, marginTop: 8, letterSpacing: '-0.02em'}}>A second check, only for amber calls</div>
            </Card>
          </Pop>
          <div style={{position: 'absolute', left: 700, top: 440, width: 520, height: 4, background: C.line, opacity: ramp(t, server + 0.2, server + 0.5) * (1 - ramp(t, out, out + 0.4))}} />
          <div style={{position: 'absolute', left: mix(680, 1080, travel), top: 380, opacity: (t > server + 0.4 ? 1 : 0) * (1 - drop), filter: drop > 0 ? `blur(${drop * 16}px)` : undefined, transform: `scale(${1 - drop * 0.4})`}}>
            <Waveform bars={14} w={160} h={120} color={C.amberBright} />
          </div>
          <div style={{position: 'absolute', left: 1262, top: 590, width: 520, fontFamily: FONT, fontSize: 28, lineHeight: 1.3, fontWeight: 650, color: C.ink, opacity: ramp(t, dropped + 0.2, dropped + 0.6) * (1 - ramp(t, out, out + 0.4))}}>
            Audio dropped after the check. No transcripts kept.
          </div>
          <Pop at={keep} out={out} from="up" style={{left: 140, top: 680}}>
            <Card style={{width: 1640, padding: '34px 44px', display: 'flex', alignItems: 'center', gap: 34, background: C.ink, color: '#fff', border: 'none'}}>
              <svg width={64} height={64} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2} strokeLinecap="round">
                <rect x="4" y="11" width="16" height="10" rx="2" />
                <path d="M8 11V7a4 4 0 0 1 8 0v4" />
              </svg>
              <div style={{flex: 1}}>
                <div style={{fontSize: 40, fontWeight: 750, letterSpacing: '-0.02em'}}>Kept: a 20 second encrypted clip, only when a scam is confirmed</div>
                <div style={{fontSize: 26, color: '#AEB8C2', marginTop: 6}}>Evidence for the bank's fraud team. Deleted after 30 days.</div>
              </div>
            </Card>
          </Pop>
        </AbsoluteFill>
      )}
      <Sfx name="whoosh" at={polite} volume={0.3} />
      <Sfx name="amber" at={rel + 0.3} volume={0.3} />
      <Sfx name="tap" at={tap1} volume={0.6} />
      <Sfx name="tap" at={yes} volume={0.6} />
      <Sfx name="clear" at={gone} volume={0.5} />
      <Sfx name="whoosh" at={server} volume={0.3} />
      <Sfx name="down" at={dropped} volume={0.35} />
      <Sfx name="pop" at={keep} volume={0.35} />
    </AbsoluteFill>
  );
};

export const S10: React.FC = () => {
  const {t, cue} = useScene();
  const name = cue('Countersign');
  const line = cue('Catch the scam');
  return (
    <AbsoluteFill>
      <Bg />
      <div style={{position: 'absolute', left: 0, right: 0, top: 300, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 36}}>
        <div style={{transform: `scale(${mix(0.7, 1, ramp(t, 0, 0.8))})`, opacity: ramp(t, 0, 0.4)}}>
          <Logo size={150} draw={ramp(t, 0.1, 1.1, EASE_IO)} />
        </div>
        <Words text="Countersign" at={name} size={130} weight={700} />
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: 520, display: 'flex', justifyContent: 'center'}}>
        <div style={{position: 'relative'}}>
          <Words text="Catch the scam while it's still a call." at={line} size={64} weight={600} color={C.ink} />
          <Underline at={line + 1} color={C.brand} />
        </div>
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: 700, textAlign: 'center', fontFamily: FONT, fontSize: 30, color: C.muted, fontWeight: 550, opacity: ramp(t, line + 1.2, line + 1.8)}}>
        Team losers · RAKSHAM finale · github.com/dope-XD/countersign
      </div>
      <Sfx name="impact" at={0} volume={0.45} />
    </AbsoluteFill>
  );
};
