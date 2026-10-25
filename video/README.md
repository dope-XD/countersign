# The Countersign video

A 2-minute explainer for the judges, made in code with [Remotion](https://www.remotion.dev) (React to MP4). The
music and sound effects are ours too, synthesised by `music/make_music.py`.

```bash
cd video && npm install
npm run build        # voice, music, render, loudness: out/countersign.mp4
npm run studio       # preview and scrub in the browser
```

- `script.json` is the voiceover, one line per scene, with delivery directions. `tools/vo.py` checks it for
  AI-sounding words, writes `SCRIPT.md` (to read aloud) and `elevenlabs/` (see `elevenlabs/ELEVENLABS.md`), and
  makes the voice: `recorded/s01.mp3` … per scene, or one `recorded/full.mp3` cut at its long pauses, or a `say`
  placeholder. It times every scene in `src/timeline.json` and pins each sentence to the pause before it, so the
  captions follow the real voice.
- `music/make_music.py` scores the music to that timeline and writes the sound effects.
- `src/scenes/` holds the ten scenes. Screens are redrawn with the app's own words and colours; the one clip marked
  "Real app, recorded" (`public/clips/not_a_scam.mp4`) is a screen recording of the app on the emulator.
- Every number on screen comes from `docs/RESULTS.md` or a named paper.
- On macOS inside a sandboxed shell, the headless browser can't start; run the render from a normal terminal.
- Licences: Remotion is free for individuals and teams of up to 3 (ours is 3). Inter and Noto Sans Devanagari are
  OFL. The music is ours. The placeholder voice is macOS `say`; the final cut uses a team member's recording.
