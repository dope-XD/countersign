"""XLS-R 300M + SLS classifier (Zhang, Wen and Hu, ACM MM 2024) on Hugging Face transformers.

The published code runs XLS-R through fairseq. This is the same network on
`transformers.Wav2Vec2Model`, so it installs on Windows and Python 3.11 and runs in
proper eval mode (the original kept dropout on at inference). Weights are mapped from
the fairseq checkpoint by `ml/port_sls_checkpoint.py`.

Input: 64,600 samples of raw 16 kHz audio (not normalised, as in the original).
Output: log-probabilities [spoof, bonafide].
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import Wav2Vec2Config, Wav2Vec2Model

N_SAMPLES = 64600
N_LAYERS = 24
DIM = 1024


def xlsr_300m_config() -> Wav2Vec2Config:
    # Same architecture as facebook/wav2vec2-xls-r-300m, written out so no download is needed.
    return Wav2Vec2Config(
        hidden_size=1024,
        num_hidden_layers=24,
        num_attention_heads=16,
        intermediate_size=4096,
        hidden_act="gelu",
        feat_extract_norm="layer",
        feat_extract_activation="gelu",
        conv_dim=(512,) * 7,
        conv_stride=(5, 2, 2, 2, 2, 2, 2),
        conv_kernel=(10, 3, 3, 3, 3, 2, 2),
        conv_bias=True,
        num_conv_pos_embeddings=128,
        num_conv_pos_embedding_groups=16,
        do_stable_layer_norm=True,
        apply_spec_augment=False,
        layerdrop=0.0,
        hidden_dropout=0.1,
        attention_dropout=0.1,
        activation_dropout=0.0,
        feat_proj_dropout=0.1,
        final_dropout=0.0,
        mask_time_prob=0.0,
    )


class SLSModel(nn.Module):
    def __init__(self, config: Wav2Vec2Config | None = None):
        super().__init__()
        self.ssl = Wav2Vec2Model(config or xlsr_300m_config())
        self.checkpointing = False
        self.first_bn = nn.BatchNorm2d(num_features=1)
        self.selu = nn.SELU(inplace=True)
        self.fc0 = nn.Linear(DIM, 1)
        self.sig = nn.Sigmoid()
        self.fc1 = nn.Linear(22847, 1024)
        self.fc3 = nn.Linear(1024, 2)
        self.logsoftmax = nn.LogSoftmax(dim=1)

    def layer_features(self, x: torch.Tensor) -> torch.Tensor:
        """Raw (pre final layer-norm) output of every transformer layer: (B, 24, T, 1024).

        Runs the encoder by hand (same ops as Wav2Vec2EncoderStableLayerNorm, no masking)
        because the HF model only exposes the last layer after its final layer-norm, and
        fairseq's layer_results, which SLS was trained on, are taken before it."""
        ssl = self.ssl
        feats = ssl.feature_extractor(x).transpose(1, 2)
        h, _ = ssl.feature_projection(feats)
        enc = ssl.encoder
        h = enc.dropout(h + enc.pos_conv_embed(h))
        outs = []
        for layer in enc.layers:
            if self.checkpointing and self.training:
                h = torch.utils.checkpoint.checkpoint(lambda t, _l=layer: _l(t)[0], h, use_reentrant=False)
            else:
                h = layer(h)[0]
            outs.append(h)
        return torch.stack(outs, dim=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        full = self.layer_features(x)  # (B, L, T, D)
        pooled = full.mean(dim=2)  # (B, L, D)  == adaptive_avg_pool1d over time
        w = self.sig(self.fc0(pooled))  # (B, L, 1)
        full = (full * w.unsqueeze(-1)).sum(dim=1)  # weighted sum over layers -> (B, T, D)
        h = self.first_bn(full.unsqueeze(1))
        h = self.selu(h)
        h = F.max_pool2d(h, (3, 3))
        h = torch.flatten(h, 1)
        h = self.selu(self.fc1(h))
        h = self.selu(self.fc3(h))
        return self.logsoftmax(h)


def fit_length(x: torch.Tensor, n: int = N_SAMPLES) -> torch.Tensor:
    """Tile short clips and cut long ones to exactly n samples, as the original data loader does."""
    if x.shape[-1] >= n:
        return x[..., :n]
    reps = n // x.shape[-1] + 1
    return x.repeat(*([1] * (x.dim() - 1)), reps)[..., :n]
