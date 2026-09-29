"""scorer.py: the counting and the statistics, checked against Hugging
Face's own detector on the same token ids. A tiny vocabulary and a word-level
tokenizer stand in for Qwen's, so nothing is downloaded."""

import copy
import re
import types

import pytest
import torch
from transformers import WatermarkDetector, WatermarkingConfig

import config as cfg
import scorer
import verdict

VOCAB = 400


class WordTokenizer:
    """One id per distinct word, with each word's characters."""

    def __init__(self):
        self.ids = {}

    def __call__(self, text, return_offsets_mapping=False):
        spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        ids = [self.ids.setdefault(text[a:b], len(self.ids) % VOCAB) for a, b in spans]
        return {"input_ids": ids, "offset_mapping": spans}


MODEL = types.SimpleNamespace(vocab_size=VOCAB, bos_token_id=None, is_encoder_decoder=False)


def settings(once=True, key=15485863):
    c = copy.deepcopy(cfg.DEFAULT_CONFIG)
    c["watermark"].update(hashing_key=key, key_id="0a1b2c3d", ignore_repeated_ngrams=once)
    return c


def make(once=True, key=15485863):
    return scorer.Scorer(settings(once, key), WordTokenizer(), MODEL)


def library_detector(conf, ignore_repeated_ngrams=False):
    wm = conf["watermark"]
    return WatermarkDetector(model_config=MODEL, device="cpu", watermarking_config=WatermarkingConfig(
        greenlist_ratio=wm["greenlist_ratio"], bias=wm["bias"], seeding_scheme=wm["seeding_scheme"],
        context_width=wm["context_width"], hashing_key=wm["hashing_key"]),
        ignore_repeated_ngrams=ignore_repeated_ngrams)


def words(n, seed=0):
    g = torch.Generator().manual_seed(seed)
    return " ".join("w{}".format(int(i)) for i in torch.randint(0, 5000, (n,), generator=g))


# ------------------------------------------------------------ the statistics
@pytest.mark.parametrize("z, p", [(0.0, 0.5), (2.0, 0.02275), (4.0, 3.167e-05), (6.0, 9.866e-10)])
def test_normal_tail(z, p):
    assert verdict.normal_tail(z) == pytest.approx(p, rel=1e-3)


def test_the_library_p_value_drops_a_square_root():
    # why scorer.py computes its own: at z = 2 the library says 0.039, not 0.023
    library = WatermarkDetector._compute_pval(None, 2.0)
    assert library == pytest.approx(0.0392, abs=1e-4)
    assert verdict.normal_tail(2.0) == pytest.approx(library / 1.72, rel=0.01)


def test_z_score():
    assert scorer.z_score(60, 100, 0.5) == pytest.approx(2.0)


# ------------------------------------------------------------ counting
def test_every_position_matches_the_library_detector():
    text = words(300)
    s = make(once=False)
    ids, _ = s.tokenize(text)
    ours = s.detect(text)
    lib = library_detector(s.config)(torch.tensor([ids]), return_dict=True)
    assert ours["num_tokens_scored"] == int(lib.num_tokens_scored[0]) == 300 - 4
    assert ours["num_green_tokens"] == int(lib.num_green_tokens[0])
    assert ours["z_score"] == pytest.approx(float(lib.z_score[0]))


def test_repeats_count_once_and_the_library_switch_does_not():
    text = " ".join(["the same sentence comes back again"] * 30)      # 6 words, 30 times
    s = make(once=True)
    ids, _ = s.tokenize(text)
    once = s.detect(text)
    # 180 tokens, 176 scored positions, but only 6 different 5-grams
    assert once["num_tokens_scored"] == 6 and once["repeated"] == 176 - 6
    lib = library_detector(s.config, ignore_repeated_ngrams=True)(torch.tensor([ids]), return_dict=True)
    assert int(lib.num_tokens_scored[0]) == 176          # tensors hash by identity: nothing is "repeated"
    every = make(once=False).detect(text)
    assert every["num_tokens_scored"] == 176 and every["repeated"] == once["repeated"]


def test_outcomes_ask_about_each_ngram_once():
    asked = []

    def green(context, token):
        asked.append((context, token))
        return token % 2 == 0
    ids = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5, 6]
    out = scorer.outcomes(ids, 5, True, green, once=True)
    assert [pos for pos, _ in out] == [4, 5, 6, 7, 8, 10]          # position 9 repeats 1 2 3 4 5
    assert len(asked) == len(set(asked)) == 6
    asked.clear()
    every = scorer.outcomes(ids, 5, True, green, once=False)
    assert [pos for pos, _ in every] == [4, 5, 6, 7, 8, 9, 10]
    assert len(asked) == 6                                        # the repeat reuses its answer


def test_a_text_too_short_to_score():
    assert make().detect("one two three four") is None
    assert make().detect("one two three four five")["num_tokens_scored"] == 1


# ------------------------------------------------------------ passages
def fake_results(pattern):
    return [(i, bool(g)) for i, g in enumerate(pattern)]


def test_best_window_finds_the_green_stretch():
    plain = [i % 2 for i in range(600)]                      # exactly half green
    block = plain[:300] + [1] * 150 + plain[450:]
    found = scorer.best_window(fake_results(block), 0.5)
    assert (found["first"], found["last"]) == (300, 449) and found["green"] == 150
    assert found["windows"] == (600 - 150) // 50 + 1
    assert scorer.best_window(fake_results(plain[:150]), 0.5) is None


def test_a_strong_passage_makes_the_verdict_likely():
    conf = settings()
    half = [i % 2 for i in range(900)]
    mixed = half[:400] + [1, 1, 1, 1, 0] * 30 + half[550:]    # 150 tokens, 80% green
    ev = scorer.evidence(fake_results(mixed), 0.5, conf)
    assert ev["z_score"] == pytest.approx(3.0) and ev["passage"]["z"] > 7.0
    assert ev["passage"]["p"] == pytest.approx(ev["passage"]["windows"] * verdict.normal_tail(ev["passage"]["z"]))
    assert ev["passage"]["decisive"] and ev["label"] == verdict.LABEL_LIKELY


def test_a_passage_never_makes_possible_and_never_lowers_a_verdict():
    conf = settings()
    half = [i % 2 for i in range(900)]
    mild = half[:400] + [1, 1, 1, 0] * 25 + half[500:]         # a weak stretch
    ev = scorer.evidence(fake_results(mild), 0.5, conf)
    assert ev["label"] == verdict.classify(ev["z_score"], 900, conf) and not ev["passage"]["decisive"]
    strong = [1, 1, 0] * 300                                    # the whole text is drafted
    ev = scorer.evidence(fake_results(strong), 0.5, conf)
    assert ev["label"] == verdict.LABEL_LIKELY and not ev["passage"]["decisive"]


def test_detect_reports_the_passage_in_characters():
    s = make()
    text = words(400, seed=3)
    stats = s.detect(text)
    passage = stats["passage"]
    ids, spans = s.tokenize(text)
    assert passage["start"] == spans[passage["first"]][0] and passage["end"] == spans[passage["last"]][1]
    assert text[passage["start"]:passage["end"]].split()[0] == text.split()[passage["first"]]
    assert "hashing_key" not in stats["watermark"]


def test_short_texts_have_no_passage():
    stats = make().detect(words(120, seed=5))
    assert stats["passage"] is None


def test_the_seed_is_the_one_the_library_uses():
    s = make()
    g = torch.Generator().manual_seed(1)
    for _ in range(20):
        context = [int(i) for i in torch.randint(0, VOCAB, (5,), generator=g)]
        library = s.processor._get_greenlist_ids(torch.tensor(context))
        rng = torch.Generator().manual_seed(s.seed(context) % (2 ** 64 - 1))
        ours = torch.randperm(VOCAB, generator=rng)[:s.processor.greenlist_size]
        assert torch.equal(library, ours)


def test_positions_that_share_a_colour_key_count_once():
    asked = []

    def green(context, token):
        asked.append(token)
        return True
    ids = [1, 2, 3, 4, 9, 5, 6, 7, 8, 9, 5, 6, 7, 8, 7]
    by_token = scorer.outcomes(ids, 5, True, green, once=True, key=lambda gram: gram[-1])
    assert [ids[pos] for pos, _ in by_token] == [9, 5, 6, 7, 8]    # later 9, 5, 6, 7, 8, 7 repeat
    assert sorted(asked) == [5, 6, 7, 8, 9]
