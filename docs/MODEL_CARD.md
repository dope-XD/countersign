# Model card: Countersign S1 (synthetic-speech detector)

**What it does:** gives the probability that a 4 s window of phone audio is machine-generated (TTS or voice conversion). It is one of four signals, and it never refuses or blocks anything by itself.

**Architecture (since 20 Oct 2026):** a score-level ensemble of two NII AntiDeepfake models, Wav2Vec2-Large (317M) and XLS-R-1B (965M). Each is a wav2vec 2.0 backbone, mean-pooled, with one linear layer. Each model's spoof log-odds is combined by a logistic regression fitted on our phone-channel dev split. Input is 16 kHz raw audio, a 64,600-sample window, layer-normed per window.

Earlier versions used XLS-R 300M + SLS (the published checkpoint, then our phone/Indic fine-tune). The ensemble replaced it after the phone-channel comparison in docs/ML.md. The old checkpoints still load.

**Training data:**
- AntiDeepfake was post-trained by NII on 56k hours of real and 18k hours of fake speech from 29 corpora in 100+ languages. These include ASVspoof 2019/2021/5, MLAAD, FLEURS and FLEURS-R, but not In-the-Wild or IndicSynth.
- We fitted only the two-model combination and its calibration. That used 3000 clips of our train split (ASVspoof 2019 LA, IndicSynth Hindi and FLEURS Hindi) through seven simulated phone channels, noisy and lossy ones included. The dev split is held out.
- No customer, bank or platform data. No IndiaCall speaker is in training.

**Licence:** the AntiDeepfake weights are CC BY-NC-SA 4.0 (NII; research and education only) and the code is BSD-3-Clause. A commercial pilot would need a licence from NII or a model trained on licensable data.

**Intended use:** risk signal in a bank contact centre and in an app's voice-note check, feeding a policy that steps up verification. It is not for identifying people, and not as sole evidence for any adverse decision.

**Known limits**
- Generators it has never seen, and heavy codecs, raise error. Open-source detectors exceed 30% EER on codec-compressed fakes (Speech DF Arena). On In-the-Wild through AMR-NB with 3% packet loss and 15 dB noise, the ensemble's EER is 9.3%. At the engine's AMBER cut-off it catches 86% of those fakes, and 61–66% of IndicSynth Hindi fakes on the same noisy channels.
- AntiDeepfake's training treated codec-compressed speech as "speech with artifacts". One member on its own (MMS-300M) flagged 26% of genuine Opus calls. The ensemble raises 0.7–3.7% of genuine In-the-Wild windows to AMBER on clean, G.711, AMR-NB and noisy channels, and 5.7% on Opus. These are per-window rates; the per-call rate comes from IndiaCall.
- FLEURS (real and resynthesised) is in AntiDeepfake's training data, so our FLEURS Hindi false-alarm numbers are optimistic. IndiaCall is the clean Indian-speech test.
- Live voice conversion by a skilled attacker can pass S1, and so can an AI voice played from a speaker into a phone mic. The app code and the signed approval on the owner's phone are what stop them.
- Noisy rooms, cheap microphones and 2G calls can raise false alarms. We measure false alarms per language and speaker and report them on `/metrics`.

**Metrics:** see `/metrics` (`models/metrics.json`). Every figure includes its test set, channel and sample size, and misses are listed.

**Fairness target:** no language, age, gender or network group above 2× the overall false-alarm rate. Measured per language and speaker at the finale; age, gender and network groups are for the pilot.

**Updates:** retrain when score drift appears or a monthly red-team with new generators finds misses. Versions are tracked in the case store (`model_version` on every case).
