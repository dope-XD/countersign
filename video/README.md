# The Countersign video

A 2-minute explainer for the judges, made in code with [Remotion](https://www.remotion.dev) (React to MP4). The
music and sound effects are ours too, synthesised by `music/make_music.py`.

```bash
cd video && npm install
npm run build        # voice, music, render, loudness: out/countersign.mp4
npm run studio       # preview and scrub in the browser
```

- `script.json` is the voiceover, one line per scene. `tools/vo.py` checks it for AI-sounding words, writes
  `SCRIPT.md` to read from, makes the voice (a recorded take from `recorded/<scene>.m4a`, or a `say` placeholder),
  and times every scene in `src/timeline.json`.
- `music/make_music.py` scores the music to that timeline and writes the sound effects.
- `src/scenes/` holds the ten scenes. Screens are redrawn with the app's own words and colours; the one clip marked
  "Real app, recorded" (`public/clips/not_a_scam.mp4`) is a screen recording of the app on the emulator.
- Every number on screen comes from `docs/RESULTS.md` or a named paper.
- On macOS inside a sandboxed shell, the headless browser can't start; run the render from a normal terminal.
- Licences: Remotion is free for individuals and teams of up to 3 (ours is 3). Inter and Noto Sans Devanagari are
  OFL. The music is ours. The placeholder voice is macOS `say`; the final cut uses a team member's recording.
