# ML: detector, data, training, evaluation

## S1 now: AntiDeepfake ensemble (20 Oct 2026)

The engine runs a score-level ensemble of NII's **AntiDeepfake** Wav2Vec2-Large and XLS-R-1B (Ge, Wang, Yamagishi et al., "Post-training for Deepfake Speech Detection", 2025; weights CC BY-NC-SA 4.0). `engine/config.py` picks it when both converted files exist and otherwise falls back to XLS-R + SLS (below).

```powershell
.venv\Scripts\python -m ml.port_antideepfake nii-yamagishilab/wav2vec-large-anti-deepfake models\s1_add_w2vlarge.pt
.venv\Scripts\python -m ml.port_antideepfake nii-yamagishilab/xls-r-1b-anti-deepfake models\s1_add_xlsr1b.pt
.venv\Scripts\python -m ml.calibrate_s1 --checkpoint models\s1_add_w2vlarge.pt,models\s1_add_xlsr1b.pt --manifest data\manifests	rain.csv --n 3000
```

- `engine/signals/antideepfake_model.py` is the released network on `transformers.Wav2Vec2Model`: per-window waveform layer-norm, final hidden states, mean over time, `Linear(D, 2)` with fake in column 0. The port reuses the fairseq key mapping from the SLS port, and fails on any unmapped or missing tensor.
- An ensemble is just comma-separated checkpoints. `ml/calibrate_s1.py` fits one logistic regression over the members' log-odds, keyed `"v1+v2"` in `models/s1_calibration.json`.
- Latency on the RTX 5070 laptop:
  - alone, one window at a time (`python -m ml.eval.latency`): p50 43 ms, p95 58 ms;
  - in the live engine, alongside ECAPA, VAD and Whisper: p95 212 ms.

**Why it replaced XLS-R + SLS.** The figures are EER, then the share of *genuine* clips that reach AMBER (window score ≥ 0.30). Each run used the same 600 + 600 In-the-Wild clips (first 4 s) and the same 174 FLEURS + 586 IndicSynth Hindi dev clips. `+loss+noise` means 15 dB coloured noise before the codec and 3% packet loss after it (`ml.augment.telephony.channel`).
Each model has its own calibration, fitted on clean codecs as of 20 Oct. The Hindi rows were scored on the clips that calibration was fitted on. [Calibration for noisy lines](#calibration-for-noisy-lines-22-oct) gives the ensemble's current numbers, including how many fakes reach each tier.

| Test set, channel | SLS published | SLS phone/Indic fine-tune | AntiDeepfake W2V-L | **W2V-L + XLS-R-1B** |
|---|---|---|---|---|
| In-the-Wild, clean | 8.0% / 54% | 8.5% / 21% | 3.2% / 0% | **2.3% / 0%** |
| In-the-Wild, G.711 | 10.7% / 71% | 10.2% / 30% | 4.0% / 0% | **2.7% / 0%** |
| In-the-Wild, AMR-NB 12.2k | 14.8% / 91% | 12.7% / 47% | 7.8% / 1% | **4.2% / 0%** |
| In-the-Wild, Opus 12k | 14.9% / 93% | 11.2% / 46% | 9.3% / 5% | **5.7% / 1%** |
| In-the-Wild, G.711 + loss + noise | 21.0% / 95% | 13.8% / 92% | 10.7% / 1% | **6.0% / 0%** |
| In-the-Wild, AMR-NB + loss + noise | 25.7% / 98% | 17.0% / 93% | 15.0% / 1% | **9.3% / 0%** |
| Hindi dev, G.711 | 44.9% / 49% | 26.4% / 16% | 0.5% / 0% | **0.0% / 0%** |
| Hindi dev, G.711 + loss + noise | 50.0% / 94% | 22.5% / 78% | 7.6% / 0% | **6.3% / 0%** |

Reading it honestly:
- **The old detector was the reason genuine calls would have been stepped up.** Whatever its EER, at the engine's AMBER cut-off it flagged 21–93% of genuine phone audio.
- **ASVspoof 2019 LA is in AntiDeepfake's training data**, so we no longer use it to compare models.
- **FLEURS is in AntiDeepfake's training data too**, so the Hindi false-alarm rate here is optimistic. IndicSynth (the Hindi fakes) is not. The clean test of genuine Indian speech is IndiaCall.
- **MMS-300M AntiDeepfake was tested and dropped.** On Opus it had a 17% EER and flagged 26% of genuine clips: the "codec = artifact" bias from its training.

Rerun: `python -m ml.eval.benchmark ... --checkpoint <ckpt[,ckpt]>` (see the docstring). Results land in `models/eval/`, with false-alarm and detection rates at both tier cut-offs.

### Calibration for noisy lines (22 Oct)

EER says how well a model separates real from fake at its best threshold. The engine doesn't get to pick that threshold: it acts at AMBER 0.30 and RED 0.70 on the calibrated score. The first ensemble calibration was fitted on clean codecs only. On a noisy, lossy line it pushed most fakes under AMBER, so the EER above looked fine while the engine missed them. We hadn't reported that column, so the table below does.

The calibration is now fitted on all seven channels, `+loss+noise` included, and on 3000 clips from **train.csv**. The AntiDeepfake models never trained on our train split, so this leaves the whole dev split held out for the Hindi rows below. Before 22 Oct the Hindi numbers were scored on the same clips the calibration was fitted on.

Each cell shows the old calibration → the new one. "Real at AMBER" is the share of genuine 4 s windows the engine would raise to AMBER. "Fakes at AMBER/RED" is the share of fake windows it raises that far. In-the-Wild is 600 + 600 clips; Hindi is 174 FLEURS + 586 IndicSynth (dev).

| Test set, channel | EER | Real at AMBER | Fakes at AMBER | Fakes at RED |
|---|---|---|---|---|
| In-the-Wild, clean | 2.3 → 2.5% | 0.2 → 0.7% | 85 → **94%** | 82 → **89%** |
| In-the-Wild, G.711 | 2.7 → 3.3% | 0.2 → 1.5% | 82 → **92%** | 79 → **85%** |
| In-the-Wild, AMR-NB 12.2k | 4.2 → 4.0% | 0.3 → 1.5% | 82 → **92%** | 75 → **87%** |
| In-the-Wild, Opus 12k | 5.7 → 4.5% | 0.8 → **5.7%** | 87 → **96%** | 84 → **91%** |
| In-the-Wild, G.711 + loss + noise | 6.0 → 5.8% | 0.2 → 2.0% | 60 → **86%** | 46 → **73%** |
| In-the-Wild, AMR-NB + loss + noise | 9.3 → 9.3% | 0.3 → 3.7% | 56 → **86%** | 39 → **71%** |
| Hindi dev, G.711 | 0.0 → 0.0% | 0.0 → 0.6% | 100 → 100% | 100 → 100% |
| Hindi dev, G.711 + loss + noise | 6.3 → 8.0% | 0.0 → 1.7% | 28 → **61%** | 15 → **36%** |
| Hindi dev, AMR-NB + loss + noise | — → 8.7% | — → 1.1% | — → **66%** | — → **42%** |

Reading it honestly:
- **The trade is worth it.** On the noisy channels, 25–35 more fakes in every 100 reach AMBER, for 2–3 more real windows in every 100.
- **Opus is the weak spot: 5.7% of real windows reach AMBER.** That is a VoIP codec. The contact-centre path is G.711 or AMR (1.5%), but voice notes from messaging apps are Opus.
- **These are per-window numbers.** A call's score is the mean of its top three windows over the last 20 s, so the call-level false-alarm rate depends on call length. Only IndiaCall measures it.
- **Noisy Hindi is still the hardest case.** About a third of IndicSynth fakes stay GREEN through G.711 with noise and loss, so the signed app approval stays mandatory for every high-risk request.
- **Hindi real-speech false alarms are still optimistic,** because FLEURS is in AntiDeepfake's training data.

### Played through a speaker into the phone (22 Oct)

The judges' test: download an AI voice and play it from a laptop speaker into the phone during a call. That puts a small loudspeaker, a room and the phone's own noise suppressor and AGC in front of the codec. ReplayDF (Müller et al., Interspeech 2025) found that this raises the best open detector's EER from 4.7% to 18.2%.

What we added:
- **`ota+<codec>` channels** (`ml/augment/telephony.py`, `over_the_air`). Fakes get:
  - a small loudspeaker: a soft-clipping amplifier, a 250–400 Hz high-pass, resonances, and a 5.5–7.5 kHz roll-off;
  - 15 cm to 1 m of synthetic room (RT60 0.15–0.6 s);
  - room noise that grows with distance;
  - the phone's capture chain: mic low-cut, a spectral noise suppressor and AGC;
  - then the codec.

  Genuine clips skip the loudspeaker and are "spoken" into the same phone from 3 to 80 cm. `ota+g711u`, `ota+amrnb_12k2` and `ota+g711u+noise` (8–15 dB room noise at 30 cm) are in `HARD_CHANNELS`, so calibration and benchmarks use them. Each is deterministic per seed.
- **Stock AI voices** (`python -m ml.tts_sets`, no cloning) → `data/manifests/tts_stock.csv`:
  - 87 Microsoft neural voices through edge-tts (en-IN, hi-IN, multilingual);
  - 46 gTTS clips (Indian, US and UK English; Hindi);
  - 90 Piper VITS clips (3 Hindi and 5 English voices).

  They read bank-call sentences in English, Hindi and Hinglish. Optional sources:
  - ElevenLabs premade voices, when `ELEVENLABS_API_KEY` is set;
  - Kokoro, if installed;
  - files you download into `data/ai_downloads/` and list in `labels.csv` (file, generator, source_url, licence);
  - MLAAD's commercial systems (below).

  Genuine rows are 174 dev-split FLEURS Hindi clips and 300 In-the-Wild English clips.
- **ReplayDF** (`python -m ml.fetch_data replaydf`, then `python -m ml.build_manifest --replaydf`). These are real re-recordings, not simulated: English bona fide speech and MLAAD fakes (Bark, VITS, XTTS v1.1, XTTS v2) played through a loudspeaker and recorded on 20 speaker/mic setups. Six of them record on an iPhone 13; the other 14 play from a laptop's own speakers. Their genuine speech was replayed too.
- **Real phone-mic recordings** (`python -m ml.ota_recordings`). This reads `data/ota/genuine/<speaker>/*.wav` and `data/ota/ai_<generator>/...` (or `labels.csv` with `ai:<generator>`). It splits whole speakers and whole generators into train and test. `calibrate_s1 --extra data/manifests/ota_real.csv` adds the train half, and `benchmark --split test --channels clean` scores the rest. No recordings exist yet.
- **`benchmark`** now breaks detection down by generator, with Wilson intervals. `--tag` keeps a snapshot out of `metrics.json`. The metrics page has a "Phone mic, played through a speaker" section.

**S1 today (the committed calibration).** Per 4 s window. Real at AMBER is the false-alarm rate, with its 95% CI. Fakes at AMBER and Fakes at RED are the detection rates. The stock voices, In-the-Wild and ReplayDF's Bark, VITS and XTTS v1.1 are held-out generators: none is in train.csv. Hindi dev holds out speakers only, since FreeVC is in train.csv, and XTTS v2 is in train.csv through IndicSynth.

| Set, channel | EER | Real at AMBER | Fakes at AMBER | Fakes at RED |
|---|---|---|---|---|
| Stock AI voices, G.711 | 4.0% | 1.3% [0.6, 2.7] | 83% | 76% |
| Stock AI voices, speaker → phone → G.711 | **40%** | 3.0% [1.8, 4.9] | **6%** | 1% |
| Stock AI voices, speaker → phone → AMR-NB | 34% | 10.5% [8.1, 13.6] | 25% | 4% |
| Stock AI voices, speaker → phone, noisy room → G.711 | 39% | 15.2% [12.2, 18.7] | 36% | 15% |
| In-the-Wild, speaker → phone → G.711 | 24% | 2.5% [1.5, 4.1] | 31% | 11% |
| Hindi dev (IndicSynth FreeVC), speaker → phone → G.711 | 33% | 2.3% [0.9, 5.8] | 7% | 2% |
| **ReplayDF, real replays, as recorded** | 18.8% | 7.6% [6.0, 9.7] | 58% | 41% |
| **ReplayDF, real replays → G.711** | 28% | 11.3% [9.2, 13.6] | 52% | 38% |

Per generator, speaker → phone → G.711: edge-tts 8% [4, 16], gTTS 4% [1, 15], Piper 6% [2, 12]. ReplayDF → G.711: Bark 70%, XTTS v1.1 62%, XTTS v2 58%, VITS 18%.

**Before/after: what we tried, judged on the held-out sets** (`python -m ml.s1_head`, `models/eval/s1_head.json`). The last column compares at equal false alarms: fakes caught at the false-alarm rate the current calibration has on that set.

| Held-out set, channel | Current calibration | Platt refit with OTA channels | Refit held at 5% false alarms | Head on frozen embeddings |
|---|---|---|---|---|
| Stock AI, speaker → phone → G.711 (real at AMBER 3.0%) | 8.5% | 8.1% (but 22% real at AMBER) | 8.1% | **50%** |
| In-the-Wild, speaker → phone → G.711 (2.5%) | 34% | 32% | 32% | **65%** |
| ReplayDF real replays, as recorded (7.6%) | 58% | 58% | 58% | 62% |
| ReplayDF real replays → G.711 (11.3%) | 52% | 54% | 54% | 51% |
| Stock AI, G.711, no speaker (1.3%) | 84% | 87% | 87% | **66%** |

- **We kept the committed calibration.** Refitting it with the over-the-air channels can only move the threshold, because the two models' scores barely separate real from fake once there is a room in the path (EER 33–40%). At AMBER the refit raised genuine windows to 16% overall on its fit set (54% on Opus) and to 22–48% on held-out over-the-air sets. Held to 5% false alarms, it catches no more than the current calibration. So `models/s1_calibration.json` is unchanged.
- **The head is not added.** It is a logistic regression on the two models' pooled embeddings, trained with the over-the-air channels, and it does catch far more *simulated* over-the-air fakes. But on real replays it is no better than the current calibration (51% vs 52% through G.711), and on plain codecs it is worse (66% vs 84%). That pattern says it learned our simulator's loudspeaker, not synthetic speech. It would also need a new engine backend. Revisit it once `data/ota` has real phone recordings to test on.
- **Room reverberation is what breaks S1.** We ran each stage alone on 150 stock fakes through G.711:

  | Stage alone | Fakes at AMBER |
  |---|---|
  | none (G.711 only) | 82% |
  | loudspeaker | 82% |
  | phone noise suppressor and AGC | 70% |
  | 20–35 dB room noise | 59% |
  | room | **13%** |

  Our synthetic rooms are not harsher than real ones. Against ReplayDF's 109 measured RIRs, median direct-to-reverberant ratio is 2.3 dB vs 2.7 dB measured, and median RT60 is 0.29 s vs 0.57 s measured.
- **Distance does not save it.** We put stock fakes at fixed distances in a dry room (RT60 0.2 s):

  | Speaker to phone | Fakes at AMBER |
  |---|---|
  | 5 cm | 39% |
  | 15 cm | 13% |
  | 30 cm | 3% |
  | 60 cm | 6% |
  | 1 m | 23% |

  At RT60 0.5 s it is 0–14% up to 60 cm. The rise at 1 m comes from room noise, which also raises genuine false alarms (10–15% in noisy rooms). This is not a detection gain.

Reading it honestly:
- **S1 alone will usually miss an AI voice played from a laptop speaker into the phone.** The best open detectors behave the same way (ReplayDF). In that test the call is stopped by the other layers: the spoken challenge and liveness checks, S2's voice-drift check, and the app passkey, which stays mandatory for every high-risk change. The demo should say so rather than imply S1 caught it.
- **The simulated channels are an estimate.** They agree with real replays on the direction and size of the damage: ReplayDF + G.711 has an EER of 28% against our simulated 24–40%. But ReplayDF uses older TTS and replays its genuine speech too, so its 11% false alarms are a worst case. The real number for our phone is the `data/ota` set once the Android app records it.
- **Small sets.** There are 223 stock fakes, and one voice reads up to 12 sentences, so the per-generator intervals are wide. Commercial TTS here means Microsoft and Google only. ElevenLabs, OpenAI and Gemini need a key or MLAAD.
- **Noisy rooms push genuine speech over AMBER** (10–15% of windows through AMR-NB or a noisy room) without catching many more fakes. That is above the 5% target, but it is per window. The call score takes the top three windows over 20 s.
- **The fix that would help is training, not calibration.** ReplayDF's own RIR-augmented retraining cut their EER from 18% to 11%. That means fine-tuning the backbones with room impulse responses: ReplayDF's 109 measured RIRs, split by setup, plus our synthetic rooms. There was no time for that before the finale.

Reproduce:
```powershell
.venv\Scripts\python -m ml.fetch_data replaydf          # 0.9 GB, CC BY-NC 4.0
.venv\Scripts\python -m ml.build_manifest --replaydf
.venv\Scripts\python -m ml.tts_sets                     # edge-tts, gTTS, Piper (+ ElevenLabs, Kokoro, MLAAD, downloads when available)
.venv\Scripts\python -m ml.eval.benchmark --manifest data\manifests\tts_stock.csv --name "Stock AI voices" --channels clean,g711u,ota+g711u,ota+amrnb_12k2,ota+g711u+noise --limit 0
.venv\Scripts\python -m ml.eval.benchmark --manifest data\manifests\replaydf.csv --name "ReplayDF (real speaker-to-mic replays)" --channels clean,g711u,amrnb_12k2 --limit 0
.venv\Scripts\python -m ml.s1_head --n 3000
.venv\Scripts\python -m ml.eval.report
```
(In-the-Wild and Hindi dev were rerun with the three `ota+` channels added to their usual lists.)

## S1 before 20 Oct: XLS-R + SLS

XLS-R 300M + SLS classifier (Zhang, Wen and Hu, ACM MM 2024; 1.92% EER on ASVspoof 2021 DF, 7.46% on In-the-Wild).

- The published code runs XLS-R through fairseq. `engine/signals/sls_model.py` is the same network on `transformers.Wav2Vec2Model`. It runs the encoder by hand so it can take each layer's output *before* the final layer-norm, which is what fairseq's `layer_results` give the SLS head.
- `ml/port_sls_checkpoint.py` maps every fairseq tensor name to the HF name and fails if any tensor is unmapped or any parameter is left empty.
- Starting weights: the MIT-licensed reproduction `sukhdeveyash/XLS-R-SLS-Deepfake-Detection` v1, trained on ASVspoof 2019 LA with RawBoost (reported 2.14% DF / 7.84% ITW).
- Inference runs fp16 on the GPU in proper eval mode (the original left dropout on), with a 64,600-sample (≈4 s) window every 2 s.

## Data (`python -m ml.fetch_data`, then `python -m ml.build_manifest`)

| Set | Use | Source |
|---|---|---|
| ASVspoof 2019 LA train | train/dev | `Bisher/ASVspoof_2019_LA` |
| IndicSynth Hindi (3 spread shards) | train/dev, spoof | `vdivyasharma/IndicSynth` (CC-BY-NC-4.0) |
| FLEURS hi_in | train/dev, **real Indian speech** | `google/fleurs` (CC-BY-4.0) |
| Kathbath Hindi (gated, optional) | train/dev, real Indian speech | `ai4bharat/Kathbath` |
| MLAAD Hindi (gated, optional) | train/dev, spoof from modern TTS | `mueller91/MLAAD` |
| MLAAD wide (gated, optional): 29 English systems incl. ElevenLabs v2/v3/Turbo, OpenAI TTS-1 HD, Gemini, Edge, Cartesia, DeepGram, MiniMax, Resemble; all 9 Hindi | test only, stock AI voices | `mueller91/MLAAD` (CC BY-NC 4.0), `python -m ml.fetch_data mlaad_wide` |
| ReplayDF, English, 20 setups (6 iPhone mics, 14 laptop speakers) | test only, real speaker-to-mic replays | `mueller91/ReplayDF` (CC BY-NC 4.0, non-commercial research) |
| Stock AI voices: edge-tts, gTTS, Piper (`ml/tts_sets.py`) | test only | generated locally; Microsoft and Google service terms, Piper voices' own licences |
| ASVspoof 2019 LA eval | test only | `SpeechAntiSpoofingBenchmarks/ASVspoof2019_LA` |
| In-the-Wild | test only | `SpeechAntiSpoofingBenchmarks/InTheWild` |
| IndiaCall | test only | our consented recordings and clones |

Real Indian speech is in training on purpose: without it the model can learn "Hindi = synthetic", because all the Hindi spoof data is synthetic.

## Fine-tuning (`python -m ml.train_s1`)

- Each clip goes through a random phone path in the DataLoader: coloured noise (RawBoost-style), then one of G.711 μ/A-law, AMR-NB 12.2/5.9/4.75k, GSM, iLBC, Opus 8/12/24k, then packet loss with concealment and a 300–3400 Hz band-limit (`ml/augment/telephony.py`, real codecs through ffmpeg).
- Balanced batches: half bona fide, half spoof, with sources drawn evenly.
- bf16 autocast, frozen CNN encoder, per-layer checkpointing, batch 8 × accumulation 4, AdamW at 2e-6 (backbone) and 2e-5 (head), cosine schedule.
- Dev EER is measured on a fixed phone-channel copy of a speaker-disjoint dev split, and the best checkpoint is kept. The baseline (starting weights) is measured first, so the log shows whether fine-tuning helped.

## Evaluation

1. `python -m ml.eval.benchmark --manifest data/manifests/itw.csv --name "In-the-Wild" --published 0.0746`
2. `python -m ml.eval.benchmark --manifest data/manifests/asv19_eval.csv --name "ASVspoof 2019 LA eval" --published 0.0287`
3. Start the engine with `.\run.ps1 -Eval`, then:
   - `python -m ml.eval.indiacall_sim --run dev --seed 7 --per-level 20 --genuine 20`
   - `python -m ml.eval.fit_fusion --dev dev`, then restart the engine
   - `python -m ml.eval.indiacall_sim --run test --seed 1`
4. `python -m ml.eval.report --indiacall test` writes `models/metrics.json`, which `/metrics` shows.

Reply delays in simulated calls are sampled. Genuine delays come from `data/indiacall/human_lags.json`, which you fill from live calls. Everything else (audio, codecs, scoring, policy, phone-key signatures) is real. The metrics page says this.
