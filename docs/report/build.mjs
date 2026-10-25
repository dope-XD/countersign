// The judges' report: report.html with the diagrams (../img/*.svg) and a QR code put inline, printed to a 2-page A4 PDF.
//   cd docs/report && npm install && npm run build      (needs Chrome: $CHROME, or the one Remotion installed for video/)
import {existsSync, readFileSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import puppeteer from 'puppeteer-core';
import QRCode from 'qrcode';

const here = dirname(fileURLToPath(import.meta.url));
const URL = 'https://github.com/dope-XD/countersign';
const chrome = [
  process.env.CHROME,
  join(here, '../../video/node_modules/.remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell'),
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
].find((p) => p && existsSync(p));
if (!chrome) throw new Error('No Chrome found: set CHROME to a Chrome or Chromium binary');

const svg = (name) => readFileSync(join(here, '../img', name), 'utf8');
const qr = await QRCode.toString(URL, {type: 'svg', margin: 0, errorCorrectionLevel: 'M', color: {dark: '#14202B', light: '#ffffff'}});
const html = readFileSync(join(here, 'report.html'), 'utf8')
  .replace('{{qr}}', qr)
  .replace('{{system}}', svg('system.svg'))
  .replace('{{timeline}}', svg('call-timeline.svg'))
  .replace('{{decision}}', svg('decision.svg'));

const browser = await puppeteer.launch({executablePath: chrome, headless: true});
const page = await browser.newPage();
await page.setContent(html, {waitUntil: 'networkidle0'});
await page.evaluate(() => document.fonts.ready);
const out = join(here, 'Countersign-report.pdf');
await page.pdf({path: out, printBackground: true, preferCSSPageSize: true});
const pages = await page.evaluate(() => document.querySelectorAll('.page').length);
const overflow = await page.evaluate(() => [...document.querySelectorAll('.page')].map((p) => p.scrollHeight - p.clientHeight));
await browser.close();
writeFileSync(join(here, 'report.built.html'), html);
console.log(`${out}: ${pages} pages; overflow per page (px): ${overflow.join(', ')}`);
if (overflow.some((o) => o > 0)) process.exitCode = 1;
