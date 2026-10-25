// Render stills at given seconds and tile them into one contact sheet, to check scenes frame by frame.
//   node tools/stills.mjs out/check.jpg 1 4.5 8 ...
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import {execFileSync} from 'node:child_process';
import {mkdirSync, rmSync} from 'node:fs';
import path from 'node:path';

const [out, ...secs] = process.argv.slice(2);
const dir = path.resolve('out/stills');
rmSync(dir, {recursive: true, force: true});
mkdirSync(dir, {recursive: true});
const serveUrl = await bundle({entryPoint: path.resolve('src/index.ts')});
const composition = await selectComposition({serveUrl, id: 'Main'});
let i = 0;
for (const s of secs) {
  const frame = Math.min(composition.durationInFrames - 1, Math.round(Number(s) * composition.fps));
  await renderStill({serveUrl, composition, frame, output: `${dir}/${String(i++).padStart(3, '0')}.jpeg`, imageFormat: 'jpeg', scale: 0.5});
}
const cols = Math.min(3, secs.length);
execFileSync('ffmpeg', ['-v', 'error', '-y', '-pattern_type', 'glob', '-i', `${dir}/*.jpeg`, '-vf', `tile=${cols}x${Math.ceil(secs.length / cols)}:padding=6:color=white`, out]);
console.log(out);
