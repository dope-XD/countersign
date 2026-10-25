import React from 'react';
import {AbsoluteFill, Audio, getStaticFiles, interpolate, Sequence, staticFile, useVideoConfig} from 'remotion';
import timeline from './timeline.json';
import {SceneProvider} from './kit/time';
import {S01, S02, S03} from './scenes/Act1';
import {S04} from './scenes/S04';
import {S05, S06} from './scenes/Act2';
import {S07, S08} from './scenes/Act3';
import {S09, S10} from './scenes/Act4';

const SCENES: Record<string, React.FC> = {s01: S01, s02: S02, s03: S03, s04: S04, s05: S05, s06: S06, s07: S07, s08: S08, s09: S09, s10: S10};

const has = (name: string) => getStaticFiles().some((f) => f.name === name);

/** The music ducks under the voice: full between lines, about −12 dB while someone speaks. */
const musicVolume = (fps: number) => (f: number) => {
  const t = f / fps;
  let duck = 0;
  for (const s of timeline.scenes) {
    const a = s.start + s.voStart;
    const b = a + s.voDur;
    const d = Math.min(ramp01(t, a - 0.35, a), 1 - ramp01(t, b, b + 0.6));
    duck = Math.max(duck, d);
  }
  const fadeIn = ramp01(t, 0, 1.5);
  const fadeOut = 1 - ramp01(t, timeline.total - 3, timeline.total);
  return 0.55 * (1 - 0.72 * duck) * fadeIn * fadeOut;
};

const ramp01 = (t: number, a: number, b: number) => interpolate(t, [a, b], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

export const Main: React.FC = () => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: '#000'}}>
      {timeline.scenes.map((s) => {
        const Scene = SCENES[s.id];
        return (
          <Sequence key={s.id} from={Math.round(s.start * fps)} durationInFrames={Math.round(s.dur * fps)} name={s.id}>
            <SceneProvider id={s.id}>
              <Scene />
            </SceneProvider>
            {has(`vo/${s.id}.wav`) && (
              <Sequence from={Math.round(s.voStart * fps)} layout="none">
                <Audio src={staticFile(`vo/${s.id}.wav`)} />
              </Sequence>
            )}
          </Sequence>
        );
      })}
      {has('audio/music.wav') && <Audio src={staticFile('audio/music.wav')} volume={musicVolume(fps)} />}
    </AbsoluteFill>
  );
};
