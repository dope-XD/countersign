import React, {createContext, useContext} from 'react';
import {Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import script from '../../script.json';
import timeline from '../timeline.json';

export const EASE = Easing.bezier(0.22, 1, 0.36, 1);
export const EASE_IN = Easing.bezier(0.6, 0, 0.9, 0.4);
export const EASE_IO = Easing.bezier(0.65, 0, 0.35, 1);

/** 0→1 between seconds a and b (clamped, eased). */
export const ramp = (t: number, a: number, b: number, ease = EASE) =>
  interpolate(t, [a, b], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});

export const mix = (a: number, b: number, p: number) => a + (b - a) * p;

export type Row = (typeof timeline.scenes)[number];

type Scene = {id: string; dur: number; vo: string; row: Row};
const SceneCtx = createContext<Scene | null>(null);

export const SceneProvider: React.FC<{id: string; children: React.ReactNode}> = ({id, children}) => {
  const row = timeline.scenes.find((s) => s.id === id)!;
  const vo = script.scenes.find((s) => s.id === id)!.vo;
  return <SceneCtx.Provider value={{id, dur: row.dur, vo, row}}>{children}</SceneCtx.Provider>;
};

/** Seconds since the scene began, the scene's length, and cue(): when a phrase of the voiceover is said. */
export const useScene = () => {
  const s = useContext(SceneCtx)!;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  // Time of a phrase, by its share of the characters spoken before it (close enough for one voice, and it follows a
  // re-recorded voice without hand-timing).
  const cue = (phrase: string, offset = 0) => {
    const i = s.vo.indexOf(phrase);
    if (i < 0) throw new Error(`cue "${phrase}" not in ${s.id}`);
    return s.row.voStart + (i / s.vo.length) * s.row.voDur + offset;
  };
  const voEnd = s.row.voStart + s.row.voDur;
  return {t, dur: s.dur, cue, voEnd, out: s.dur - 0.45};
};
