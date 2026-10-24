"""Over-the-air channel, stock-TTS manifest, phone-mic recordings and the report's phone-mic
section (no models, no network)."""

import csv
import random

import numpy as np
import pytest
import soundfile as sf

from ml import ota_recordings, tts_sets
from ml.augment import telephony as T
from ml.eval import benchmark, report

SR = 16000


def _speech_like(n=SR * 3, seed=0):
    """Voiced bursts with pauses: enough structure for the noise suppressor and AGC to act on."""
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    env = (np.sin(2 * np.pi * 1.5 * t) > 0).astype(np.float32)
    x = sum(np.sin(2 * np.pi * f * t) / (k + 1) for k, f in enumerate((140, 280, 420, 900, 2200)))
    return (0.3 * env * x / np.max(np.abs(x)) + 0.002 * rng.standard_normal(n)).astype(np.float32)


def _band_db(x, lo, hi):
    f = np.fft.rfftfreq(len(x), 1 / SR)
    p = np.abs(np.fft.rfft(x)) ** 2
    return 10 * np.log10(np.sum(p[(f >= lo) & (f < hi)]) + 1e-12)


# ------------------------------------------------------------------ OTA channel
@pytest.mark.parametrize("name", ["ota+g711u", "ota+g711u+noise", "ota+clean"])
@pytest.mark.parametrize("genuine", [False, True])
def test_ota_channel_is_deterministic_and_keeps_length(name, genuine):
    x = _speech_like()
    a = T.channel(x, name, seed=11, genuine=genuine)
    b = T.channel(x, name, seed=11, genuine=genuine)
    c = T.channel(x, name, seed=12, genuine=genuine)
    assert a.dtype == np.float32 and len(a) == len(x) and np.isfinite(a).all()
    assert np.array_equal(a, b) and not np.allclose(a, c)
    assert np.max(np.abs(a)) <= 1.0


def test_ota_channels_are_registered_for_calibration_and_benchmarks():
    assert set(T.OTA_CHANNELS) == {"ota+g711u", "ota+amrnb_12k2", "ota+g711u+noise"}
    assert set(T.OTA_CHANNELS) <= set(T.HARD_CHANNELS)
    from ml.calibrate_s1 import CHANNELS

    assert set(T.OTA_CHANNELS) <= set(CHANNELS)


def test_genuine_only_changes_the_ota_channels():
    x = _speech_like()
    assert np.array_equal(T.channel(x, "g711u+loss+noise", 3), T.channel(x, "g711u+loss+noise", 3, genuine=True))
    assert not np.allclose(T.channel(x, "ota+clean", 3), T.channel(x, "ota+clean", 3, genuine=True))


def test_small_loudspeaker_has_no_bass():
    t = np.arange(SR) / SR
    x = 0.3 * np.sin(2 * np.pi * 100 * t) + 0.3 * np.sin(2 * np.pi * 1000 * t)
    y = T.small_loudspeaker(x, random.Random(0))
    drop_100 = _band_db(x, 80, 120) - _band_db(y, 80, 120)
    drop_1k = _band_db(x, 900, 1100) - _band_db(y, 900, 1100)
    assert drop_100 - drop_1k > 15


@pytest.mark.parametrize("rt60", [0.15, 0.6])
def test_room_ir_decays_at_its_rt60_and_far_means_more_reverb(rt60):
    rng, g = random.Random(1), np.random.default_rng(1)
    h = T.room_ir(rt60, 0.5, rng, g)
    d0 = int(np.argmax(np.abs(h)))
    tail = h[d0 + int(0.03 * SR) :]
    # energy 60 dB down after RT60 (Schroeder integral, with slack for the random tail)
    edc = 10 * np.log10(np.cumsum(tail[::-1] ** 2)[::-1] / np.sum(tail**2) + 1e-12)
    assert edc[min(len(edc) - 1, int((rt60 - 0.03) * SR))] < -30

    def drr(dist):
        h = T.room_ir(rt60, dist, random.Random(2), np.random.default_rng(2))
        k = int(np.argmax(np.abs(h)))
        return h[k] ** 2 / np.sum(np.delete(h, k) ** 2)

    assert drr(0.05) > 10 * drr(0.8)


def test_phone_mic_agc_lifts_a_quiet_talker():
    x = 0.01 * _speech_like()
    y = T.phone_mic(x.astype(np.float64), random.Random(0))
    assert np.sqrt(np.mean(y**2)) > 5 * np.sqrt(np.mean(x**2))
    assert np.max(np.abs(y)) <= 0.95


# ------------------------------------------------------------------ stock-TTS manifest
def test_generator_family():
    assert tts_sets.family("edge-tts") == tts_sets.family("ElevenLabs-v3") == tts_sets.family("OpenAI TTS-1 HD") == "commercial"
    assert tts_sets.family("piper-vits") == tts_sets.family("xtts_v2") == tts_sets.family("freevc24") == "open"
    assert tts_sets.family("") == tts_sets.family("unknown") == "unknown"


def test_trim_cuts_silence_around_speech():
    x = np.concatenate([np.zeros(SR), _speech_like(SR), np.zeros(SR)])
    y = tts_sets.trim(x)
    assert SR <= len(y) < 1.2 * SR


@pytest.fixture
def tts_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_sets, "ROOT", tmp_path)
    monkeypatch.setattr(tts_sets, "CLIPS", tmp_path / "data" / "clips" / "tts_stock")
    monkeypatch.setattr(tts_sets, "DOWNLOADS", tmp_path / "data" / "ai_downloads")
    monkeypatch.setattr(tts_sets, "MAN", tmp_path / "data" / "manifests")
    return tmp_path


def test_downloads_become_spoof_rows_cut_into_clips(tts_dirs):
    d = tts_dirs / "data" / "ai_downloads"
    d.mkdir(parents=True)
    sf.write(d / "eleven_long.wav", np.tile(_speech_like(SR * 2), 7), SR)  # 14 s -> 2 clips of 6 s
    sf.write(d / "sarvam.wav", _speech_like(SR * 2), SR)
    with open(d / "labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "generator", "source_url", "licence", "language"])
        w.writerow(["eleven_long.wav", "ElevenLabs", "https://example.org/a", "demo", "en"])
        w.writerow(["sarvam.wav", "Sarvam-Bulbul", "https://example.org/b", "demo", "hi"])
        w.writerow(["missing.wav", "x", "", "", ""])
    rows = tts_sets.downloads()
    assert [r["generator"] for r in rows] == ["elevenlabs", "elevenlabs", "sarvam-bulbul"]
    assert {r["label"] for r in rows} == {"spoof"} and {r["split"] for r in rows} == {"eval"}
    assert {r["source"] for r in rows} == {"ai_downloads"}
    assert rows[0]["speaker"] == rows[1]["speaker"] == "eleven_long" and rows[2]["language"] == "hi"
    for r in rows:
        x, sr = sf.read(tts_dirs / r["path"])
        assert sr == SR and SR <= len(x) <= 6 * SR
    assert all(tts_sets.family(r["generator"]) == "commercial" for r in rows)


def test_manifest_keeps_rows_of_generators_not_rerun(tts_dirs, monkeypatch):
    def fake(gen):
        return lambda per_voice: [tts_sets.row(f"data/clips/tts_stock/{gen}/a.flac", "v1", "en", tts_sets.LABEL[gen])]

    monkeypatch.setattr(tts_sets, "GENERATORS", {"edge": fake("edge"), "gtts": fake("gtts")})
    monkeypatch.setattr(tts_sets, "genuine", lambda n: [{**tts_sets.row("data/clips/x.flac", "s", "hi", "-"), "label": "bonafide"}])
    monkeypatch.setattr("sys.argv", ["tts_sets", "edge", "gtts"])
    tts_sets.main()
    monkeypatch.setattr("sys.argv", ["tts_sets", "gtts"])
    tts_sets.main()
    with open(tts_dirs / "data" / "manifests" / "tts_stock.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert sorted(r["generator"] for r in rows) == ["-", "edge-tts", "gtts"]
    assert list(rows[0]) == ["path", "label", "speaker", "language", "generator", "source", "split"]


# ------------------------------------------------------------------ phone-mic recordings
def test_parse_label():
    assert ota_recordings.parse_label("genuine") == ("bonafide", "-")
    assert ota_recordings.parse_label("ai:ElevenLabs") == ("spoof", "elevenlabs")
    assert ota_recordings.parse_label("ai_edge-tts") == ("spoof", "edge-tts")
    assert ota_recordings.parse_label("ai-gtts") == ("spoof", "gtts")
    assert ota_recordings.parse_label("misc") is None and ota_recordings.parse_label("ai_") is None


def test_ota_recordings_scan_and_split_hold_out_whole_groups(tmp_path, monkeypatch):
    monkeypatch.setattr(ota_recordings, "ROOT", tmp_path)
    root = tmp_path / "data" / "ota"
    for folder, n in (("genuine/asha", 3), ("genuine/ravi", 2), ("genuine/meera", 2), ("ai_elevenlabs/rachel", 2), ("ai-gtts", 2), ("notes", 1)):
        (root / folder).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (root / folder / f"c{i}.wav").write_bytes(b"\0")
    (root / "extra").mkdir()
    (root / "extra" / "x.wav").write_bytes(b"\0")
    (root / "labels.csv").write_text("file,label,speaker\nextra/x.wav,ai:openai,alloy\n", encoding="utf-8")
    rows = ota_recordings.scan(root)
    assert len(rows) == 12  # the unlabelled "notes" folder is skipped
    gens = {r["generator"] for r in rows if r["label"] == "spoof"}
    assert gens == {"elevenlabs", "gtts", "openai"}
    assert {r["speaker"] for r in rows if r["generator"] == "gtts"} == {"c0", "c1"}
    rows = ota_recordings.split(rows, seed=0)
    for key, label in (("speaker", "bonafide"), ("generator", "spoof")):
        groups = {}
        for r in rows:
            if r["label"] == label:
                groups.setdefault(r[key], set()).add(r["split"])
        assert all(len(s) == 1 for s in groups.values())  # a group is never on both sides
        assert {"train", "test"} <= set().union(*groups.values())


# ------------------------------------------------------------------ benchmark + report
def test_by_generator_counts_fakes_at_amber_with_intervals():
    rows = [{"label": "spoof", "generator": "edge-tts"}] * 4 + [{"label": "spoof", "generator": ""}] * 2 + [{"label": "bonafide", "generator": "-"}]
    scores = np.array([0.9, 0.8, 0.1, 0.35, 0.95, 0.2, 0.99])
    out = {g["generator"]: g for g in benchmark.by_generator(rows, scores)}
    assert set(out) == {"edge-tts", "unknown"}
    e = out["edge-tts"]
    assert (e["n"], e["k"], e["family"], e["detect_red"]) == (4, 3, "commercial", 0.5)
    assert e["ci"][0] < 0.75 < e["ci"][1]
    assert out["unknown"]["family"] == "unknown"


def _run(name, manifest, results):
    return {"set": name, "manifest": manifest, "model": "m", "results": results}


def _res(cond, n_bona, fa, gens):
    return {
        "condition": cond,
        "n_bona": n_bona,
        "n_spoof": sum(g[1] for g in gens),
        "false_alarm_amber": fa,
        "by_generator": [
            {"generator": g, "family": tts_sets.family(g), "n": n, "k": k, "detect_amber": k / n, "detect_red": 0.0, "ci": [0, 1]} for g, n, k in gens
        ],
    }


def test_phone_mic_section_pools_families_and_keeps_real_recordings_apart():
    runs = [
        _run(
            "Stock AI voices",
            "data/manifests/tts_stock.csv",
            [_res("g711u", 100, 0.01, [("edge-tts", 10, 9)]), _res("ota+g711u", 100, 0.04, [("edge-tts", 10, 5), ("piper-vits", 20, 10)])],
        ),
        _run("Hindi dev", "data/manifests/dev.csv", [_res("ota+g711u", 50, 0.10, [("freevc24", 30, 3)])]),
        _run(
            "ReplayDF", "data\\manifests\\replaydf.csv", [{**_res("g711u", 800, 0.2, [("bark", 200, 50)]), "eer": 0.2, "detect_amber": 0.25, "detect_red": 0.1}]
        ),
    ]
    pm = report.phone_mic_section(runs)
    fam = {(f["condition"], f["family"]): f for f in pm["families"]}
    assert set(fam) == {("ota+g711u", "commercial"), ("ota+g711u", "open")}  # plain codec channels stay out
    assert (fam["ota+g711u", "open"]["n"], fam["ota+g711u", "open"]["k"]) == (50, 13)
    assert {g["generator"] for g in pm["generators"]} == {"edge-tts", "piper-vits", "freevc24"}
    assert [(g["set"], g["k"], g["n"]) for g in pm["genuine"]] == [("Stock AI voices", 4, 100), ("Hindi dev", 5, 50)]
    assert pm["genuine_target_met"] is False  # Hindi dev: 10% of genuine clips at AMBER
    assert [(r["kind"], r["condition"]) for r in pm["real"]] == [("replaydf", "g711u")]
    assert report.phone_mic_section([_run("x", "a.csv", [_res("g711u", 10, 0.0, [])])]) is None
