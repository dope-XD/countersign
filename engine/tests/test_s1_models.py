"""S1 architecture plumbing (no real weights): AntiDeepfake key mapping, checkpoint loading
by "arch", and the fixed phone paths the benchmark uses."""

import numpy as np
import pytest
import torch

from engine.signals.antideepfake_model import AntiDeepfakeModel, backbone_config
from engine.signals.s1_synth import S1Detector, build_model
from ml.augment.telephony import channel
from ml.port_antideepfake import map_add_key

TINY = {
    "hidden_size": 32,
    "num_hidden_layers": 2,
    "num_attention_heads": 2,
    "intermediate_size": 64,
    "conv_dim": [32] * 7,
    "conv_kernel": [10, 3, 3, 3, 3, 2, 2],
    "conv_stride": [5, 2, 2, 2, 2, 2, 2],
    "conv_bias": True,
    "num_conv_pos_embeddings": 16,
    "num_conv_pos_embedding_groups": 2,
    "do_stable_layer_norm": True,
    "feat_extract_norm": "layer",
    "mask_time_prob": 0.075,  # as in the released configs; must be switched off for inference
    "architectures": ["Wav2Vec2ForPreTraining"],
}


def test_fairseq_keys_map_onto_the_hf_backbone():
    tkeys = set(AntiDeepfakeModel(backbone_config(TINY)).state_dict())
    cases = {
        "proj_fc.weight": "head.weight",
        "m_ssl.model.feature_extractor.conv_layers.0.0.weight": "ssl.feature_extractor.conv_layers.0.conv.weight",
        "m_ssl.model.feature_extractor.conv_layers.3.2.1.bias": "ssl.feature_extractor.conv_layers.3.layer_norm.bias",
        "m_ssl.model.post_extract_proj.weight": "ssl.feature_projection.projection.weight",
        "m_ssl.model.layer_norm.weight": "ssl.feature_projection.layer_norm.weight",
        "m_ssl.model.encoder.layer_norm.bias": "ssl.encoder.layer_norm.bias",
        "m_ssl.model.encoder.layers.1.self_attn.k_proj.weight": "ssl.encoder.layers.1.attention.k_proj.weight",
        "m_ssl.model.encoder.layers.0.fc2.bias": "ssl.encoder.layers.0.feed_forward.output_dense.bias",
        "m_ssl.model.encoder.layers.0.final_layer_norm.weight": "ssl.encoder.layers.0.final_layer_norm.weight",
    }
    for src, want in cases.items():
        got = map_add_key(src, tkeys)
        assert got == want, (src, got)
        assert got in tkeys
    assert map_add_key("m_ssl.model.quantizer.vars", tkeys) is None
    assert map_add_key("m_ssl.model.mask_emb", tkeys) is None


def test_inference_config_has_no_masking_or_dropout():
    cfg = backbone_config(TINY)
    assert cfg.mask_time_prob == 0.0 and not cfg.apply_spec_augment
    assert cfg.layerdrop == 0.0 and cfg.hidden_dropout == 0.0


def test_antideepfake_checkpoint_loads_and_scores(tmp_path):
    model = AntiDeepfakeModel(backbone_config(TINY))
    path = tmp_path / "s1_add_tiny.pt"
    torch.save({"arch": "antideepfake", "config": TINY, "state_dict": model.state_dict(), "version": "add-tiny-test"}, path)

    rebuilt, arch = build_model(torch.load(path, weights_only=False))
    assert arch == "antideepfake" and isinstance(rebuilt, AntiDeepfakeModel)

    det = S1Detector()
    det.load(path)
    assert det.backend == "antideepfake" and det.version == "add-tiny-test"
    x = np.random.default_rng(0).standard_normal(64600).astype(np.float32) * 0.1
    z = det.log_odds([x, x * 3])
    # the waveform is layer-normed per clip, so loudness alone can't move the score
    assert abs(z[0] - z[1]) < 1e-2
    p = det.score([x])[0].p_synthetic
    assert 0.0 <= p <= 1.0


def test_old_sls_checkpoints_still_default_to_sls():
    _, arch = build_model({"state_dict": {}})
    assert arch == "sls"


def test_hard_channels_are_deterministic_and_keep_length():
    x = np.sin(np.linspace(0, 3000, 32000)).astype(np.float32) * 0.3
    a = channel(x, "clean+loss+noise", seed=7)
    b = channel(x, "clean+loss+noise", seed=7)
    c = channel(x, "clean+loss+noise", seed=8)
    assert len(a) == len(x)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    assert not np.allclose(a, x)
    g = channel(x, "g711u+noise", seed=1)
    assert abs(len(g) - len(x)) <= 2


def test_genuine_only_volunteers_are_never_cloned(tmp_path, monkeypatch):
    from engine import indiacall
    from ml.clones import generate

    monkeypatch.setattr(indiacall, "ROOT", tmp_path)
    monkeypatch.setattr(generate, "IC", tmp_path)
    indiacall.record_consent("volunteer1", "A Volunteer", ["hi"], clone=False, age_band="60+")
    indiacall.record_consent("teammate1", "A Teammate", ["hi"], clone=True)
    assert not generate.may_clone("volunteer1")
    assert generate.may_clone("teammate1")
    assert not generate.may_clone("nobody")
    with pytest.raises(SystemExit):
        generate.check_consent("volunteer1")
