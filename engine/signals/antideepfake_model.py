"""AntiDeepfake (Ge, Wang, Yamagishi et al., NII 2025) on Hugging Face transformers.

Wav2Vec 2.0 / XLS-R / MMS backbones post-trained for deepfake detection on 74k hours in
100+ languages. The released code builds the backbone in fairseq; this is the same network
on `transformers.Wav2Vec2Model`: whole-input layer-norm of the waveform, the backbone's
final hidden states (after the encoder's last layer-norm, like fairseq's features_only
output), mean over time, one linear layer. Weights are mapped by `ml/port_antideepfake.py`.

Licence: weights CC BY-NC-SA 4.0 (research and education only), code BSD-3-Clause.

Input: raw 16 kHz audio, any length (we use the same 64,600-sample window as SLS).
Output: logits [fake, real].
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import Wav2Vec2Config, Wav2Vec2Model

# inference-only overrides on top of the repo's config.json
_EVAL_OVERRIDES = {
    "apply_spec_augment": False,
    "mask_time_prob": 0.0,
    "layerdrop": 0.0,
    "hidden_dropout": 0.0,
    "attention_dropout": 0.0,
    "activation_dropout": 0.0,
    "feat_proj_dropout": 0.0,
    "final_dropout": 0.0,
}


def backbone_config(cfg: dict) -> Wav2Vec2Config:
    keep = {k: v for k, v in cfg.items() if not k.startswith("_") and k not in ("architectures", "transformers_version", "torch_dtype")}
    return Wav2Vec2Config(**{**keep, **_EVAL_OVERRIDES})


class AntiDeepfakeModel(nn.Module):
    def __init__(self, config: Wav2Vec2Config):
        super().__init__()
        self.ssl = Wav2Vec2Model(config)
        self.head = nn.Linear(config.hidden_size, 2)
        self.checkpointing = False

    def set_checkpointing(self, on: bool) -> None:
        self.checkpointing = on
        if on:
            self.ssl.gradient_checkpointing_enable()
        else:
            self.ssl.gradient_checkpointing_disable()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = F.layer_norm(x, x.shape[-1:])  # per clip, as the reference loader does
        h = self.ssl(x).last_hidden_state  # (B, T, D)
        return self.head(h.mean(dim=1))  # (B, 2) logits [fake, real]
