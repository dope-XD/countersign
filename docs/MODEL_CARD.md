# Model card: Countersign S1 (synthetic-speech detector)

**What it does:** gives the probability that a 4 s window of phone audio is machine-generated (TTS or voice conversion). It is one of four signals, and it never refuses or blocks anything by itself.

**Architecture:** XLS-R 300M (Meta, wav2vec 2.0) + SLS layer-weighting classifier, about 316M parameters, input 16 kHz raw audio, 64,600 samples.

**Training data:** ASVspoof 2019 LA, IndicSynth Hindi, FLEURS Hindi, and optionally Kathbath Hindi and MLAAD Hindi, all through simulated phone channels. No customer, bank or platform data. No IndiaCall speaker is in training.

**Intended use:** risk signal in a bank contact centre and in an app's voice-note check, feeding a policy that steps up verification. It is not for identifying people, and not as sole evidence for any adverse decision.

**Known limits**
- Generators it has never seen, and heavy codecs, raise error. Open-source detectors exceed 30% EER on codec-compressed fakes (Speech DF Arena).
- Live voice conversion by a skilled attacker can pass S1. The passkey step-up is what stops it.
- Noisy rooms, cheap microphones and 2G calls can raise false alarms. We measure false alarms per language and speaker and report them on `/metrics`.

**Metrics:** see `/metrics` (`models/metrics.json`). Every figure includes its test set, channel and sample size, and misses are listed.

**Fairness target:** no language, age, gender or network group above 2× the overall false-alarm rate. Measured per language and speaker at the finale; age, gender and network groups are for the pilot.

**Updates:** retrain when score drift appears or a monthly red-team with new generators finds misses. Versions are tracked in the case store (`model_version` on every case).
