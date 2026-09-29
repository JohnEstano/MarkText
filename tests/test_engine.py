"""Pure parts of engine.py: no model is loaded here."""
import copy
import json

import pytest
import torch

import config as cfg
import engine
import main
import verdict


CFG = {"detection_threshold": 4.0, "possible_threshold": 2.0, "min_tokens_for_verdict": 100}


@pytest.mark.parametrize("z, tokens, label", [
    (6.55, 277, engine.LABEL_LIKELY),
    (4.0, 296, engine.LABEL_LIKELY),          # boundary is inclusive
    (3.99, 296, engine.LABEL_POSSIBLE),
    (2.0, 296, engine.LABEL_POSSIBLE),
    (1.16, 325, engine.LABEL_NOT_DETECTED),
    (-1.29, 196, engine.LABEL_NOT_DETECTED),
    (1.72, 41, engine.LABEL_INCONCLUSIVE),    # the 41-token CSV row
    (9.0, 99, engine.LABEL_INCONCLUSIVE),     # short text is inconclusive even with high z
])
def test_classify_bands(z, tokens, label):
    assert engine.classify(z, tokens, CFG) == label


def test_classify_reads_thresholds_from_config():
    assert engine.classify(3.0, 500, {"detection_threshold": 2.5, "possible_threshold": 1.0,
                                      "min_tokens_for_verdict": 0}) == engine.LABEL_LIKELY


def test_resolve_device_rejects_unknown():
    assert engine._resolve_device("cpu") == "cpu"
    assert engine._resolve_device("AUTO") in ("cpu", "cuda")
    with pytest.raises(ValueError):
        engine._resolve_device("mps")


def test_sidecar_round_trip(tmp_path):
    txt = tmp_path / "marktext_watermarked_x.txt"
    txt.write_text("hello", encoding="utf-8")
    info = {"text": "hello", "mode": "watermarked", "seed": 42, "watermark": {"bias": 3.0}}
    side = main.write_sidecar(txt, info)
    assert side.name == "marktext_watermarked_x.json"
    data = json.loads(side.read_text(encoding="utf-8"))
    assert "text" not in data and data["seed"] == 42 and data["text_file"] == txt.name
    assert main.read_sidecar(txt)["mode"] == "watermarked"
    assert main.read_sidecar(tmp_path / "nothing.txt") is None


def test_labels_and_classify_are_reexported_from_verdict():
    assert engine.classify is verdict.classify
    assert engine.LABELS == verdict.LABELS


def test_placeholder_stats_are_inconclusive_and_keyless():
    c = copy.deepcopy(cfg.DEFAULT_CONFIG)
    c["watermark"]["hashing_key"] = 987654321
    stats = verdict.placeholder_stats(c, "cpu")
    assert stats["label"] == verdict.LABEL_INCONCLUSIVE and stats["num_tokens_scored"] == 0
    assert "987654321" not in json.dumps(stats)


class _Batch(dict):
    def to(self, device):
        return self


class _FakeTokenizer:
    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        return "prompt"

    def __call__(self, text, return_tensors):
        return _Batch(input_ids=torch.tensor([[1, 2, 3]]))

    def decode(self, ids, skip_special_tokens):
        return "decoded text"


class _FakeModel:
    def generate(self, **kwargs):
        return torch.tensor([[1, 2, 3, 4, 5]])


def test_generate_result_never_contains_the_hashing_key():
    eng = engine.Engine.__new__(engine.Engine)          # no model download
    eng.config = copy.deepcopy(cfg.DEFAULT_CONFIG)
    eng.config["watermark"].update(hashing_key=123456789, key_id="0a1b2c3d")
    eng.device = "cpu"
    eng.tokenizer, eng.model, eng.watermark_config = _FakeTokenizer(), _FakeModel(), object()
    out = eng.generate("hi", max_new_tokens=5, watermarked=True, seed=1)
    dumped = json.dumps(out)
    assert "hashing_key" not in dumped and "123456789" not in dumped
    assert out["watermark"]["key_id"] == "0a1b2c3d" and out["new_tokens"] == 2
