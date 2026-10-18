// 8 kHz mu-law from the other party -> speaker, with a small jitter buffer.
const IN_RATE = 8000;
const DEC = new Float32Array(256);
for (let i = 0; i < 256; i++) {
  const u = ~i & 0xff;
  const sign = u & 0x80, exp = (u >> 4) & 7, mant = u & 0x0f;
  let s = (((mant << 3) + 0x84) << exp) - 0x84;
  DEC[i] = (sign ? -s : s) / 32768;
}

class Playback extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Float32Array(IN_RATE * 2);
    this.w = 0; this.r = 0; this.count = 0;
    this.step = IN_RATE / sampleRate;
    this.frac = 0;
    this.primed = false;
    this.port.onmessage = (e) => {
      const bytes = new Uint8Array(e.data);
      for (let i = 0; i < bytes.length; i++) {
        if (this.count >= this.buf.length) { this.r = (this.r + 1) % this.buf.length; this.count--; }
        this.buf[this.w] = DEC[bytes[i]];
        this.w = (this.w + 1) % this.buf.length;
        this.count++;
      }
    };
  }
  process(_inputs, outputs) {
    const out = outputs[0][0];
    if (!this.primed && this.count >= 960) this.primed = true; // 120 ms jitter buffer
    for (let i = 0; i < out.length; i++) {
      if (!this.primed || this.count < 2) { out[i] = 0; if (this.count < 2) this.primed = false; continue; }
      const a = this.buf[this.r], b = this.buf[(this.r + 1) % this.buf.length];
      out[i] = a + (b - a) * this.frac;
      this.frac += this.step;
      while (this.frac >= 1) { this.frac -= 1; this.r = (this.r + 1) % this.buf.length; this.count--; }
    }
    for (let c = 1; c < outputs[0].length; c++) outputs[0][c].set(out);
    return true;
  }
}
registerProcessor('playback-8k', Playback);
