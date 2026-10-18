# ML: detector, data, training, evaluation

## S1 detector

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
