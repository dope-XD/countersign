"""IndiaCall eval tooling: plan building, report aggregation and the fusion fit (no engine, no audio)."""

import dataclasses
import json
import random
from collections import Counter

import numpy as np
import pytest

from engine import fusion
from engine.indiacall import OPENINGS, challenges
from engine.mocks.world import FRI_SEED, SEED
from ml.eval import fit_fusion, report
from ml.eval.indiacall_sim import ATTACKER_OWN, GENUINE_OTHER, REGISTERED, TTS_GENERATORS, build_plans, plan_summary

OPS = [o[0] for o in OPENINGS]
CHS = list(challenges())


def _files(d, names):
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / f"{n}.wav").write_bytes(b"\0" * 2000)


@pytest.fixture
def indiacall(tmp_path):
    """alice: cloned by every tool; bob: one TTS clone with openings only; vol: genuine-only volunteer;
    half: recorded openings but no challenge yet."""
    rec, clones = tmp_path / "recordings", tmp_path / "clones"
    for s in ("alice", "bob", "vol"):
        _files(rec / s, OPS + CHS)
    _files(rec / "half", OPS)
    for g in [*TTS_GENERATORS, "seedvc"]:
        _files(clones / g / "alice", OPS + CHS + ["P01"])
    _files(clones / "xtts" / "bob", OPS)
    return rec, clones, tmp_path


def test_numbers_line_up_with_the_mock_world():
    assert SEED["rahul"].registered_mobile == REGISTERED
    assert GENUINE_OTHER not in FRI_SEED and all(c.registered_mobile != GENUINE_OTHER for c in SEED.values())
    assert FRI_SEED[ATTACKER_OWN] == "High"


def test_build_plans_spreads_genuine_calls_and_skips_uncloned_speakers(indiacall):
    rec, clones, data = indiacall
    plans = build_plans(10, 120, seed=3, rec=rec, clones=clones, data=data)
    gen = [p for p in plans if p.level == "genuine"]
    assert len(gen) == 120
    # every speaker with an opening and a challenge, evenly; "half" has no challenge yet
    assert Counter(p.speaker for p in gen) == {"alice": 40, "bob": 40, "vol": 40}
    assert Counter(p.cli_kind for p in gen) == {"registered": 96, "other": 24}
    assert {p.cli for p in gen if p.cli_kind == "other"} == {GENUINE_OTHER}

    by_level = {lvl: [p for p in plans if p.level == lvl] for lvl in ("L1", "L2", "L3", "L4")}
    assert {p.speaker for p in by_level["L1"]} == {"alice", "bob"}
    assert all(p.speaker == "alice" for lvl in ("L2", "L3", "L4") for p in by_level[lvl])
    assert not any(p.speaker in ("vol", "half") for p in plans if p.level != "genuine")
    for lvl in ("L1", "L2", "L3"):
        assert len(by_level[lvl]) == 10
        assert Counter(p.cli_kind for p in by_level[lvl]) == {"registered": 5, "other": 5}
        assert {p.cli for p in by_level[lvl] if p.cli_kind == "other"} == {ATTACKER_OWN}
    assert all(p.cli == REGISTERED and p.sim_swap for p in by_level["L4"])
    assert all(p.generator == "xtts" for p in by_level["L1"] if p.speaker == "bob")
    assert {p.generator for p in by_level["L2"]} == set(TTS_GENERATORS)
    # recorded per result and deterministic for a seed
    assert dataclasses.asdict(plans[0])["cli_kind"] in ("registered", "other")
    assert [dataclasses.asdict(p) for p in plans] == [dataclasses.asdict(p) for p in build_plans(10, 120, seed=3, rec=rec, clones=clones, data=data)]
    assert plan_summary(plans)["calls"]["genuine/registered"] == 96


def test_build_plans_with_no_clones_plans_genuine_only(indiacall):
    rec, _, data = indiacall
    plans = build_plans(5, 12, seed=1, rec=rec, clones=data / "nothing", data=data)
    assert len(plans) == 12 and {p.level for p in plans} == {"genuine"}


def test_build_plans_uses_measured_lags_when_present(indiacall):
    rec, clones, data = indiacall
    (data / "human_lags.json").write_text(json.dumps([0.71, 0.72]))
    gen = [p for p in build_plans(0, 6, seed=1, rec=rec, clones=clones, data=data) if p.level == "genuine"]
    assert {p.lag for p in gen} <= {0.71, 0.72}


# ------------------------------------------------------------------ report
def _row(level, cli, final, speaker="alice", lang="en", executed=None, tiers=None):
    return {
        "plan": {
            "id": f"{level}-{random.random():.6f}",
            "level": level,
            "speaker": speaker,
            "generator": "xtts",
            "cli": cli,
            "cli_kind": "registered" if cli == REGISTERED else "other",
        },
        "language": lang,
        "final_tier": final,
        "tiers_seen": tiers if tiers is not None else ([] if final == "GREEN" else [final]),
        "reasons": [],
        "features": {"s1": 0.5},
        "executed": (level == "genuine") if executed is None else executed,
    }


def test_report_separates_genuine_numbers_and_shows_detection_only():
    rows = (
        [_row("genuine", REGISTERED, "GREEN") for _ in range(95)]
        + [_row("genuine", REGISTERED, "AMBER") for _ in range(5)]
        + [_row("genuine", GENUINE_OTHER, "AMBER") for _ in range(20)]
        + [_row("L1", REGISTERED, "GREEN") for _ in range(3)]
        + [_row("L1", REGISTERED, "RED") for _ in range(7)]
        + [_row("L1", ATTACKER_OWN, "AMBER") for _ in range(10)]
        + [{**_row("L2", REGISTERED, "RED"), "error": "boom"}]
    )
    out = report.summarise(rows)
    reg, other = out["genuine"]["by_cli"]
    assert (reg["cli_kind"], reg["n"], reg["k"]) == ("registered", 100, 5) and reg["rate"] == pytest.approx(0.05)
    assert reg["ci"][0] < 0.05 < reg["ci"][1]
    assert (other["n"], other["k"]) == (20, 20)
    target = next(t for t in out["targets"] if "registered number given" in t["name"])
    assert target["pass"] is True and "95% CI" in target["result"]
    # fairness is about registered-number calls only
    assert next(f for f in out["fairness"] if f["group"] == "English")["n"] == 100

    det = {(d["level"], d["cli_kind"]): d for d in out["detection"]}
    assert set(det) == {("L1", "registered"), ("L1", "other")}
    assert (det["L1", "registered"]["k"], det["L1", "registered"]["red"], det["L1", "registered"]["ended_green"]) == (7, 7, 3)
    assert det["L1", "other"]["rate"] == 1.0 and det["L1", "other"]["ended_green"] == 0
    assert next(t for t in out["targets"] if "spoofed caller ID" in t["name"])["result"] == "3 of 10"
    # other-number genuine calls reaching AMBER are expected, not misses
    assert sum(m["level"] == "genuine" for m in out["misses"]) == 5
    assert out["errors"] == 1


def test_report_counts_the_highest_tier_reached():
    assert report.reached(_row("L3", REGISTERED, "RED", tiers=["AMBER", "RED"])) == "RED"
    assert report.reached(_row("L3", REGISTERED, None, tiers=[])) == "none"


def test_lag_note_says_what_was_measured():
    assert "placeholder" in report.lag_note({"human_lags": {"measured": 0, "placeholder": "x"}})
    note = report.lag_note({"human_lags": {"measured": 24, "placeholder": None}})
    assert "24 reply delays measured on live" in note and "placeholder" not in note


# ------------------------------------------------------------------ fusion fit
def test_loso_splits_hold_out_each_speaker_once():
    groups = ["a", "b", "a", "c", "b"]
    splits = fit_fusion.loso_splits(groups)
    assert [s for s, _, _ in splits] == ["a", "b", "c"]
    for s, tr, te in splits:
        assert all(groups[i] == s for i in te) and all(groups[i] != s for i in tr)
        assert sorted([*tr, *te]) == list(range(len(groups)))


@pytest.mark.parametrize("n", [10, 19, 20, 57, 120])
def test_pick_amber_keeps_genuine_under_the_budget(n):
    scores = np.random.default_rng(n).beta(2, 8, n)
    cut = fit_fusion.pick_amber(scores, 0.05, floor=0.0)
    assert np.mean(scores >= cut) <= 0.05
    assert np.sum(scores >= cut) == int(0.05 * n + 1e-9)  # and no stricter than it has to be


def test_pick_amber_handles_ties_and_floor():
    assert np.mean(np.array([0.2] * 30) >= fit_fusion.pick_amber(np.array([0.2] * 30), 0.05, floor=0.0)) == 0
    assert fit_fusion.pick_amber(np.array([0.01] * 40), 0.05, floor=0.1) == 0.1


def _sim_rows(rng, speakers=("a", "b", "c", "d"), n_gen=30, n_att=20):
    rows = []
    for s in speakers:
        for i in range(n_gen):
            rows.append(
                {
                    "plan": {"level": "genuine", "speaker": s, "cli": REGISTERED if i % 5 else GENUINE_OTHER},
                    "features": {"s1": float(rng.beta(1, 12)), "drift": float(rng.uniform(0.1, 0.4))},
                    "liveness": {"passed": True, "reasons": []},
                }
            )
        for i in range(n_att):
            rows.append(
                {
                    "plan": {"level": "L2", "speaker": s, "cli": ATTACKER_OWN},
                    "features": {"s1": float(rng.beta(6, 3)), "drift": float(rng.uniform(0.3, 0.8))},
                    "liveness": {"passed": False, "reasons": ["RESP_LAG"] if i % 2 else []},
                }
            )
    rows.append({"plan": {"level": "genuine", "speaker": "vol", "cli": REGISTERED}, "features": {"s1": 0.05, "drift": None}, "liveness": None})
    return rows


def test_fit_refits_drift_and_reports_leave_one_speaker_out():
    rows = _sim_rows(np.random.default_rng(0))
    out = fit_fusion.fit(rows, max_genuine_amber=0.05)
    drifts = [r["features"]["drift"] for r in rows if r["plan"]["level"] == "genuine" and r["features"]["drift"] is not None]
    assert out["drift_threshold"] == pytest.approx(np.percentile(drifts, 99)) and out["drift_threshold"] != fusion.FusionWeights().drift_threshold
    folds = {f["speaker"]: f for f in out["cv"]["folds"]}
    assert set(folds) == {"a", "b", "c", "d", "vol"}
    assert folds["vol"]["attacks"] == 0 and folds["vol"]["auc"] is None
    pooled = out["cv"]["pooled"]
    assert pooled["genuine_registered_amber_or_red"] <= 0.05 and pooled["auc"] > 0.9
    assert 0.1 <= out["amber_at"] < out["red_at"] <= 0.95
    assert out["w1"] >= 0.1 and out["w2"] >= 0 and out["w3"] >= 0


def test_fusion_reads_fitted_cutoffs(tmp_path, monkeypatch):
    (tmp_path / "fusion.json").write_text(json.dumps({"w1": 1.0, "b": 0.0, "amber_at": 0.6, "red_at": 0.9, "cv": {}}))
    monkeypatch.setattr(fusion, "settings", dataclasses.replace(fusion.settings, models_dir=tmp_path))
    w = fusion.FusionWeights.load()
    assert (w.amber_at, w.red_at) == (0.6, 0.9)
    monkeypatch.setattr(fusion, "weights", w)
    assert fusion.fuse([0.5], None, None, []).tier == "GREEN"  # r = 0.5 is under the fitted AMBER cut-off
    assert fusion.fuse([0.8], None, None, []).tier == "AMBER"
    monkeypatch.setenv("COUNTERSIGN_AMBER_AT", "0.3")
    assert fusion.FusionWeights.load().amber_at == fusion.FusionWeights().amber_at  # explicit override wins
