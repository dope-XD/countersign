// The paper: figures (fig/*.svg, from figures.py) → vector PDFs, then paper.tex → Countersign-paper.pdf with Tectonic.
//   cd docs/paper && npm install && npm run build      (needs Chrome: $CHROME or the one Remotion installed for video/,
//   python, and tectonic: brew install tectonic)
import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync, readdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import puppeteer from 'puppeteer-core';

const here = dirname(fileURLToPath(import.meta.url));
const chrome = [
  process.env.CHROME,
  join(here, '../../video/node_modules/.remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell'),
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
].find((p) => p && existsSync(p));
if (!chrome) throw new Error('No Chrome found: set CHROME to a Chrome or Chromium binary');

const python = [join(here, '../../.venv/bin/python'), join(here, '../../../Countersign/.venv/bin/python'), 'python3'].find((p) => p === 'python3' || existsSync(p));
execFileSync(python, [join(here, 'figures.py')], {stdio: 'inherit'});

const browser = await puppeteer.launch({executablePath: chrome, headless: true});
const page = await browser.newPage();
for (const f of readdirSync(join(here, 'fig')).filter((n) => n.endsWith('.svg'))) {
  const svg = readFileSync(join(here, 'fig', f), 'utf8');
  const [, w, h] = svg.match(/viewBox="0 0 (\d+) (\d+)"/);
  await page.setContent(`<html><body style="margin:0">${svg}</body></html>`);
  await page.pdf({path: join(here, 'fig', f.replace('.svg', '.pdf')), width: `${w}px`, height: `${h}px`, printBackground: true, pageRanges: '1'});
}
await browser.close();

execFileSync('tectonic', ['-X', 'compile', '--keep-logs', 'paper.tex'], {cwd: here, stdio: 'inherit'});
execFileSync('mv', [join(here, 'paper.pdf'), join(here, 'Countersign-paper.pdf')]);
console.log(join(here, 'Countersign-paper.pdf'));
