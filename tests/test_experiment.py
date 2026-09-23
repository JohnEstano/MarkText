import json
import threading

import pandas as pd
import pytest

import experiment
import history


@pytest.fixture
def hist(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "logs" / "h.csv")
    monkeypatch.setattr(history, "EXPORT_DIR", tmp_path / "logs" / "exports")
    monkeypatch.setattr(experiment, "EXPORT_DIR", tmp_path / "logs" / "exports")
    return history


class FakeEngine:
    """Deterministic stand-in: watermarked text scores high, normal low."""
    device = "cpu"
    config = {"model_id": "fake", "detection_threshold": 4.0, "possible_threshold": 2.0,
              "min_tokens_for_verdict": 100,
              "watermark": {"bias": 3.0, "greenlist_ratio": 0.5, "seeding_scheme": "selfhash",
                            "context_width": 5, "hashing_key": 1}}

    def __init__(self):
        self.calls = []

    def generate(self, prompt, max_new_tokens=None, watermarked=True, seed=None, cancel_event=None):
        self.calls.append((prompt, max_new_tokens, watermarked, seed))
        text = ("wm " if watermarked else "nm ") * max_new_tokens
        return {"text": text, "new_tokens": max_new_tokens, "cancelled": False, "mode":
                "watermarked" if watermarked else "normal"}

    def detect(self, text):
        n = len(text.split())
        z = 6.0 if text.startswith("wm") else -0.5
        label = "INCONCLUSIVE (short text)" if n < 100 else ("LIKELY MARKTEXT" if z >= 4 else "NOT DETECTED")
        return {"num_tokens_scored": n - 4, "num_green_tokens": int(n * 0.7), "green_fraction": 0.7,
                "z_score": z, "p_value": 1e-9 if z > 4 else 0.7, "label": label,
                "device": "cpu", "watermark": {"bias": 3.0, "greenlist_ratio": 0.5,
                                               "seeding_scheme": "selfhash", "context_width": 5}}


def test_load_prompts(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("﻿one\n\n# comment\ntwo\nthree\n", encoding="utf-8")
    assert experiment.load_prompts(f) == ["one", "two", "three"]
    assert experiment.load_prompts(f, limit=2) == ["one", "two"]


def test_run_batch_logs_every_cell_with_sequential_seeds(hist, tmp_path):
    eng = FakeEngine()
    pf = tmp_path / "p.txt"; pf.write_text("a\nb\n", encoding="utf-8")
    bid = experiment.run_batch(eng, ["a", "b"], [50, 150], runs=1, seed_base=100, prompt_file=pf)
    rows = [r for r in hist.read_history() if r["batch_id"] == bid]
    assert len(rows) == 2 * 2 * 2
    seeds = {int(r["seed"]) for r in rows}
    assert len(seeds) == 8                                   # one distinct seed per cell
    assert all(100 <= s < 100 + 1_000_000 for s in seeds)
    assert experiment.cell_seed(100, 0, 50, "normal", 0) == experiment.cell_seed(100, 0, 50, "normal", 0)
    assert experiment.cell_seed(100, 0, 50, "normal", 0) != experiment.cell_seed(101, 0, 50, "normal", 0)
    assert {r["source"] for r in rows} == {"batch"}
    assert experiment.settings_path(bid).exists()
    assert json.loads(experiment.settings_path(bid).read_text())["seed_base"] == 100
    assert "hashing_key" not in json.loads(experiment.settings_path(bid).read_text())["watermark"]


def test_run_batch_resumes_without_duplicates(hist, tmp_path):
    eng = FakeEngine()
    pf = tmp_path / "p.txt"; pf.write_text("a\nb\nc\n", encoding="utf-8")
    cancel = threading.Event()
    seen = []

    def stop_after_three(done, total, row):
        seen.append(done)
        if done == 3:
            cancel.set()
    bid = experiment.run_batch(eng, ["a", "b", "c"], [50], runs=1, seed_base=7,
                               on_progress=stop_after_three, cancel_event=cancel, prompt_file=pf)
    assert len([r for r in hist.read_history() if r["batch_id"] == bid]) == 3
    experiment.run_batch(eng, ["a", "b", "c"], [50], runs=1, batch_id=bid, prompt_file=pf)
    rows = [r for r in hist.read_history() if r["batch_id"] == bid]
    assert len(rows) == 6
    cells = {(json.loads(r["note"])["p"], int(r["max_new_tokens"]), r["mode"]) for r in rows}
    assert len(cells) == 6                       # no duplicates
    # extending the grid keeps every existing cell's seed
    experiment.run_batch(eng, ["a", "b", "c"], [50, 150], runs=1, batch_id=bid, prompt_file=pf)
    rows2 = {json.loads(r["note"])["p"]: r for r in hist.read_history()
             if r["batch_id"] == bid and r["max_new_tokens"] == "50" and r["mode"] == "normal"}
    assert {k: v["seed"] for k, v in rows2.items()} == {
        json.loads(r["note"])["p"]: r["seed"] for r in rows if r["max_new_tokens"] == "50" and r["mode"] == "normal"}
    assert len([r for r in hist.read_history() if r["batch_id"] == bid]) == 12


def test_summarise_batch_rates():
    df = pd.DataFrame({
        "run_id": list("abcdefgh"),
        "mode": ["watermarked"] * 4 + ["normal"] * 4,
        "max_new_tokens": [150] * 8,
        "gen_tokens": [150] * 8,
        "context_width": [5] * 8,
        "tokens_scored": [146] * 7 + [140],           # one round-trip mismatch
        "green_pct": [70, 68, 72, 55, 50, 49, 52, 60],
        "z_score": [6.0, 5.5, 6.2, 1.5, -0.3, 0.2, 0.4, 2.5],
        "result": ["LIKELY MARKTEXT"] * 3 + ["NOT DETECTED"] + ["NOT DETECTED"] * 3 + ["POSSIBLE WATERMARK"],
    })
    cfg = {"detection_threshold": 4.0, "possible_threshold": 2.0}
    s = experiment.summarise_batch(df, cfg).set_index("mode")
    assert s.loc["watermarked", "flagged_rate"] == 0.75
    assert s.loc["normal", "flagged_rate"] == 0.0
    assert s.loc["normal", "possible_or_above_rate"] == 0.25
    assert s.loc["normal", "retokenize_mismatch"] == 1
    assert s.loc["watermarked", "n"] == 4
    assert "TP rate" in s.loc["watermarked", "rate_meaning"]


def test_plan_cells_order():
    cells = experiment.plan_cells(2, [50, 150], 1, ("normal", "watermarked"))
    assert cells[0] == (0, 50, "normal", 0) and cells[-1] == (1, 150, "watermarked", 0)
    assert len(cells) == 8
