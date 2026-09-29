"""A golden score. One committed human essay, scored with the real Qwen
tokenizer under a fixed public test key, must give exactly these numbers.

It pins everything the scorer takes from transformers: the tokenisation,
the green lists and the seed formula. An upgrade that changes any of them
fails here, instead of silently changing verdicts on old submissions.
Counting every position must also still match the library's own detector.

Needs the tokenizer and the model's configuration (about 10 MB, never the
weights). Skipped when they are not in the Hugging Face cache and cannot be
downloaded.
"""

import copy
import pathlib
import types

import pytest
import torch

import config as cfg
import scorer

ROOT = pathlib.Path(__file__).resolve().parent.parent
ESSAY = ROOT / "classroom" / "demo_texts" / "alice.txt"
TEST_KEY = 15485863          # Hugging Face's public default key: fine for a test, never for use


@pytest.fixture(scope="module")
def qwen():
    transformers = pytest.importorskip("transformers")
    model_id = cfg.DEFAULT_CONFIG["model_id"]
    for local in (True, False):
        try:
            return (transformers.AutoTokenizer.from_pretrained(model_id, local_files_only=local),
                    transformers.AutoConfig.from_pretrained(model_id, local_files_only=local))
        except Exception:
            continue
    pytest.skip("the Qwen tokenizer is not available (no cache, no network)")


def score(qwen, once):
    config = copy.deepcopy(cfg.DEFAULT_CONFIG)
    config["watermark"].update(hashing_key=TEST_KEY, key_id="0a1b2c3d", ignore_repeated_ngrams=once)
    return scorer.Scorer(config, *qwen).detect(ESSAY.read_text(encoding="utf-8"))


def test_the_golden_essay_counting_each_colour_once(qwen):
    stats = score(qwen, once=True)
    assert (stats["input_tokens"], stats["num_tokens_scored"], stats["num_green_tokens"],
            stats["repeated"]) == (228, 195, 101, 29)
    assert stats["z_score"] == pytest.approx(0.50128, abs=1e-5)
    assert stats["label"] == "NOT DETECTED" and stats["passage"] is not None


def test_the_golden_essay_counting_every_position_matches_the_library(qwen):
    stats = score(qwen, once=False)
    assert (stats["num_tokens_scored"], stats["num_green_tokens"]) == (224, 108)
    assert stats["z_score"] == pytest.approx(-0.534522, abs=1e-5)
    from transformers import WatermarkDetector, WatermarkingConfig
    tokenizer, model_config = qwen
    wm = cfg.DEFAULT_CONFIG["watermark"]
    detector = WatermarkDetector(model_config=types.SimpleNamespace(
        vocab_size=model_config.vocab_size, bos_token_id=model_config.bos_token_id,
        is_encoder_decoder=False), device="cpu", watermarking_config=WatermarkingConfig(
        greenlist_ratio=wm["greenlist_ratio"], bias=wm["bias"], seeding_scheme=wm["seeding_scheme"],
        context_width=wm["context_width"], hashing_key=TEST_KEY))
    ids = tokenizer(ESSAY.read_text(encoding="utf-8"), return_tensors="pt")["input_ids"]
    library = detector(ids, return_dict=True)
    assert (int(library.num_tokens_scored[0]), int(library.num_green_tokens[0])) == (224, 108)
    assert torch.is_tensor(ids)
