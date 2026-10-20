# ML: detector, data, training, evaluation

## S1 now: AntiDeepfake ensemble (20 Oct 2026)

The engine runs a score-level ensemble of NII's **AntiDeepfake** Wav2Vec2-Large and XLS-R-1B (Ge, Wang, Yamagishi et al., "Post-training for Deepfake Speech Detection", 2025; weights CC BY-NC-SA 4.0). `engine/config.py` picks it when both converted files exist and otherwise falls back to XLS-R + SLS (below).

```powershell
.venv\Scripts\python -m ml.port_antideepfake nii-yamagishilab/wav2vec-large-anti-deepfake models\s1_add_w2vlarge.pt
.venv\Scripts\python -m ml.port_antideepfake nii-yamagishilab/xls-r-1b-anti-deepfake models\s1_add_xlsr1b.pt
.venv\Scripts\python -m ml.calibrate_s1 --checkpoint models\s1_add_w2vlarge.pt,models\s1_add_xlsr1b.pt
```

- `engine/signals/antideepfake_model.py` is the released network on `transformers.Wav2Vec2Model`: per-window waveform layer-norm, final hidden states, mean over time, `Linear(D, 2)` with fake in column 0. The port reuses the fairseq key mapping from the SLS port, and fails on any unmapped or missing tensor.
- An ensemble is just comma-separated checkpoints. `ml/calibrate_s1.py` fits one logistic regression over the members' log-odds, keyed `"v1+v2"` in `models/s1_calibration.json`.
- Latency on the RTX 5070 laptop:
  - alone, one window at a time (`python -m ml.eval.latency`): p50 43 ms, p95 58 ms;
  - in the live engine, alongside ECAPA, VAD and Whisper: p95 212 ms.

**Why it replaced XLS-R + SLS.** The figures are EER, then the share of *genuine* clips that reach AMBER (window score ≥ 0.30). Each run used the same 600 + 600 In-the-Wild clips (first 4 s) and the same 174 FLEURS + 586 IndicSynth Hindi dev clips. `+loss+noise` means 15 dB coloured noise before the codec and 3% packet loss after it (`ml.augment.telephony.channel`).

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

Reply delays in simulated calls are sampled. Genuine delays come from `data/indiacall/human_lags.json`, which you fill from live calls. Everything else (audio, codecs, scoring, policy, passkey signatures) is real. The metrics page says this.
