// Mic (or injected file) -> 8 kHz G.711 mu-law, 20 ms frames, exactly like a phone line.
const OUT_RATE = 8000;
const FRAME = 160; // 20 ms at 8 kHz

function designLowpass(rate, cutoff, taps) {
  const h = new Float32Array(taps);
  const m = (taps - 1) / 2;
  let sum = 0;
  for (let i = 0; i < taps; i++) {
    const x = i - m;
    const sinc = x === 0 ? 2 * cutoff / rate : Math.sin(2 * Math.PI * cutoff * x / rate) / (Math.PI * x);
    const w = 0.54 - 0.46 * Math.cos(2 * Math.PI * i / (taps - 1));
    h[i] = sinc * w;
    sum += h[i];
  }
  for (let i = 0; i < taps; i++) h[i] /= sum;
  return h;
}

function mulaw(s) {
  let pcm = Math.max(-32768, Math.min(32767, Math.round(s * 32768)));
  const sign = pcm < 0 ? 0x80 : 0;
  let mag = Math.min(Math.abs(pcm), 32635) + 0x84;
  let exp = 7;
  for (let mask = 0x4000; (mag & mask) === 0 && exp > 0; exp--, mask >>= 1) {}
  const mant = (mag >> (exp + 3)) & 0x0f;
  return ~(sign | (exp << 4) | mant) & 0xff;
}

class Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / OUT_RATE;
    this.h = designLowpass(sampleRate, 3600, 63);
    this.hist = new Float32Array(this.h.length);
    this.hpos = 0;
    this.n = 0; // input samples seen
    this.next = 0; // input position of next output sample
    this.frame = new Uint8Array(FRAME);
    this.fi = 0;
    this.muted = false;
    this.level = 0;
    this.port.onmessage = (e) => { if (e.data && 'muted' in e.data) this.muted = e.data.muted; };
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    const L = this.h.length;
    let peak = 0;
    for (let i = 0; i < ch.length; i++) {
      const v = this.muted ? 0 : ch[i];
      if (Math.abs(v) > peak) peak = Math.abs(v);
      this.hist[this.hpos] = v;
      this.hpos = (this.hpos + 1) % L;
      this.n++;
      if (this.n >= this.next) {
        this.next += this.step;
        let acc = 0;
        for (let k = 0; k < L; k++) acc += this.h[k] * this.hist[(this.hpos + k) % L];
        this.frame[this.fi++] = mulaw(acc);
        if (this.fi === FRAME) {
          this.port.postMessage(this.frame.buffer.slice(0));
          this.fi = 0;
        }
      }
    }
    this.level = Math.max(peak, this.level * 0.9);
    if ((this.n & 2047) < ch.length) this.port.postMessage({ level: this.level });
    return true;
  }
}
registerProcessor('capture-8k', Capture);
