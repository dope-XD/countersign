// Colours from the app (android/.../ui/Theme.kt), plus the dark act.
import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import {loadFont as loadDeva} from '@remotion/google-fonts/NotoSansDevanagari';

export const inter = loadInter('normal', {weights: ['400', '500', '600', '700', '800'], subsets: ['latin']}).fontFamily;
export const deva = loadDeva('normal', {weights: ['500', '600', '700'], subsets: ['devanagari', 'latin']}).fontFamily;
export const FONT = `${inter}, ${deva}, sans-serif`;
export const HINDI = `${deva}, ${inter}, sans-serif`;

export const C = {
  brand: '#0B5CAD',
  brandSoft: '#E6EEF7',
  ink: '#14202B',
  muted: '#5B6B79',
  paper: '#F4F6F8',
  line: '#D5DBE1',
  white: '#FFFFFF',
  green: '#137A3F',
  greenSoft: '#E3F4E9',
  amber: '#9A5B00',
  amberSoft: '#FFF1D6',
  amberBright: '#F2A42B',
  red: '#B3261E',
  redSoft: '#FCE4E2',
  guardRed: '#9F1D17',
  grey: '#4A5560',
  greySoft: '#ECEFF2',
  // the dark act
  night: '#0B0E13',
  night2: '#151A22',
  nightCard: '#1A2029',
  nightLine: '#2A323D',
  nightText: '#E9EDF2',
  nightMuted: '#8893A0',
};

export const W = 1920;
export const H = 1080;
