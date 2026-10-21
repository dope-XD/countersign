# web

The browser side of Countersign: the caller softphone, the agent console, the bank app, the fraud desk, the demo panel, the metrics page and the IndiaCall recorder. React 19, Vite and Tailwind. There's no state library: each page polls or subscribes to the engine's `/ws/events` topics.

```powershell
npm install
npm run dev      # http://localhost:5173, proxies /api and /ws to the engine on :8000
npm run build    # web/dist, which the engine serves in production
npm run lint
```

The engine has to be running for anything to work (`..\run.ps1`, or `..\run.ps1 -Dummy` without a GPU).

Points that aren't obvious from the code:

- Call audio is G.711 μ-law at 8 kHz in 20 ms frames, both ways. `public/worklets/capture.js` downsamples the mic from the AudioContext rate. `public/worklets/playback.js` is a small jitter buffer. Both are plain JS AudioWorklets so Vite doesn't bundle them.
- Passkeys use `@simplewebauthn/browser`. The engine builds the WebAuthn options and checks the result, so the client only passes JSON through. Passkeys need HTTPS (or localhost) and a stable hostname. See `docs/RUNBOOK.md`.
- Staff pages sit behind `components/StaffGate.tsx`, which swaps the PIN for an HttpOnly cookie.
