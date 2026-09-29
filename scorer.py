"""Scoring a text for MarkText's watermark, one visible step at a time.

What decides the colour of a token comes from Hugging Face: the same
WatermarkLogitsProcessor that biases generation says which tokens are green
after a given context. The counting and the statistics are done here,
because two parts of the library's WatermarkDetector do not do what they
say (transformers/generation/watermarking.py, 5.17):
- `ignore_repeated_ngrams` puts n-gram tensors in a collections.Counter;
  tensors hash by identity, so no two n-grams are ever equal and repeats
  are counted every time (line 160).
- `_compute_pval` drops the square root from Polya's approximation of the
  normal tail (lines 187-189): at z = 2 it returns 0.039 instead of 0.023,
  at z = 6 it returns 5e-11 instead of 1e-9.

The test (Kirchenbauer et al. 2023, arXiv:2301.10226):
1. Tokenise the text. Each position after the first context_width - 1
   tokens is "scored": its n-gram (the context and the token itself, for
   selfhash) decides whether the token is green.
2. A repeated n-gram is counted once (arXiv:2306.04634, the paper the
   library's own docstring cites): its colour is fixed by the key, so a
   second copy of a phrase is not new evidence, and counting it again
   inflates z for text that repeats itself.
3. Without the watermark each distinct n-gram is green with probability
   gamma (the greenlist ratio), so with T scored and G green:
       z = (G - gamma*T) / sqrt(T * gamma * (1 - gamma))
   and the one-sided p-value is the normal tail P(Z >= z).
   The verdict for the whole text is the same rule as always: z against
   the thresholds in the config (4.0 likely, 2.0 possible).
4. Passages. A student may paste an assistant draft into a longer essay,
   and the whole-text z dilutes it. Windows of WINDOW scored tokens, one
   every STEP tokens, are scored as well. Looking at k windows is k tests,
   so the best window's p-value is multiplied by k (Bonferroni) before it
   is compared with the "likely" threshold's p-value (z 4.0 -> 3.2e-5).
   A passage can raise the verdict to "likely", never lower it, and never
   produces "possible". So for text without the watermark the chance of
   "likely" is at most twice one test's (6.3 in 100,000, the union bound)
   and the chance of "possible" is unchanged (2.3%). In simulation, a
   200-token assistant passage in a 1000-token essay is found as "likely"
   about 7 times in 10; the whole-text z alone finds it about 6 times in 100.
"""

import math

import torch
from transformers import AutoConfig, AutoTokenizer, WatermarkLogitsProcessor

import config as cfg
import verdict

WINDOW = verdict.PASSAGE_WINDOW      # scored tokens per passage window
STEP = verdict.PASSAGE_STEP          # a new window every STEP scored tokens


def z_score(green, total, gamma):
    return (green - gamma * total) / math.sqrt(total * gamma * (1 - gamma))


def outcomes(ids, n, selfhash, is_green, once=True):
    """[(position, green)] for each scored position in text order, where
    position is the index of the scored token. With once=True an n-gram
    seen earlier in the text is skipped. is_green(context, token) -> bool."""
    seen = {}
    out = []
    for end in range(n - 1, len(ids)):
        gram = tuple(ids[end - n + 1:end + 1])
        repeat = gram in seen
        if repeat and once:
            continue
        if not repeat:
            seen[gram] = bool(is_green(gram if selfhash else gram[:-1], gram[-1]))
        out.append((end, seen[gram]))
    return out


def best_window(results, gamma, size=WINDOW, step=STEP):
    """The window of `size` consecutive scored tokens with the most green
    ones, trying one every `step` tokens and one ending at the last token.
    None when the text has no more scored tokens than one window."""
    total = len(results)
    if total <= size:
        return None
    starts = list(range(0, total - size + 1, step))
    if starts[-1] != total - size:
        starts.append(total - size)
    running = [0]
    for _, green in results:
        running.append(running[-1] + green)
    best = max(starts, key=lambda s: running[s + size] - running[s])
    green = running[best + size] - running[best]
    return {"first": results[best][0], "last": results[best + size - 1][0], "tokens": size,
            "green": green, "z": z_score(green, size, gamma), "windows": len(starts)}


def evidence(results, gamma, config, size=WINDOW, step=STEP):
    """The whole-text numbers and verdict, and the strongest passage with
    its Bonferroni-corrected p-value; a passage past the "likely"
    threshold makes the verdict "likely" (passage["decisive"])."""
    total = len(results)
    green = sum(g for _, g in results)
    z = z_score(green, total, gamma)
    label = verdict.classify(z, total, config)
    passage = best_window(results, gamma, size, step)
    if passage is not None:
        passage["p"] = min(1.0, passage["windows"] * verdict.normal_tail(passage["z"]))
        passage["decisive"] = (label in (verdict.LABEL_POSSIBLE, verdict.LABEL_NOT_DETECTED)
                               and passage["p"] <= verdict.likely_p(config))
        if passage["decisive"]:
            label = verdict.LABEL_LIKELY
    return {"num_tokens_scored": total, "num_green_tokens": green,
            "green_fraction": green / total, "z_score": z, "p_value": verdict.normal_tail(z),
            "passage": passage, "label": label}


class Scorer:
    """Scores texts. Needs the tokenizer and the model's configuration (its
    vocabulary size), never the model weights, so scoring can start before
    the model has loaded and does not wait for a generation."""

    device = "cpu"

    def __init__(self, config, tokenizer=None, model_config=None):
        self.config = config
        self.tokenizer = tokenizer or AutoTokenizer.from_pretrained(config["model_id"])
        model_config = model_config or AutoConfig.from_pretrained(config["model_id"])
        self.bos_token_id = model_config.bos_token_id
        wm = config["watermark"]
        self.gamma = float(wm["greenlist_ratio"])
        self.selfhash = wm["seeding_scheme"] == "selfhash"
        # tokens in one n-gram: with selfhash the scored token is part of its own context
        self.n = int(wm["context_width"]) + (0 if self.selfhash else 1)
        self.min_tokens = self.n
        self.once = bool(wm.get("ignore_repeated_ngrams", True))
        self.processor = WatermarkLogitsProcessor(
            vocab_size=model_config.vocab_size, device="cpu",
            greenlist_ratio=wm["greenlist_ratio"], bias=wm["bias"],
            hashing_key=wm["hashing_key"], seeding_scheme=wm["seeding_scheme"],
            context_width=wm["context_width"])

    def is_green(self, context, token):
        greenlist = self.processor._get_greenlist_ids(torch.tensor(context, dtype=torch.long))
        return bool((greenlist == token).any())

    def tokenize(self, text):
        """Token ids and each token's (start, end) characters in `text`."""
        enc = self.tokenizer(text, return_offsets_mapping=True)
        ids, spans = list(enc["input_ids"]), list(enc["offset_mapping"])
        if ids and ids[0] == self.bos_token_id:          # as the library's detector does
            ids, spans = ids[1:], spans[1:]
        return ids, spans

    def detect(self, text):
        """None when the text is too short to score at all, otherwise the
        statistics (see evidence()) plus where the strongest passage is."""
        ids, spans = self.tokenize(text)
        if len(ids) < self.min_tokens:
            return None
        results = outcomes(ids, self.n, self.selfhash, self.is_green, self.once)
        stats = evidence(results, self.gamma, self.config)
        grams = [tuple(ids[end - self.n + 1:end + 1]) for end in range(self.n - 1, len(ids))]
        passage = stats["passage"]
        if passage is not None:
            passage.update(start=int(spans[passage["first"]][0]), end=int(spans[passage["last"]][1]))
        stats.update({
            "repeated": len(grams) - len(set(grams)),        # positions whose n-gram came earlier
            "prediction": stats["label"] == verdict.LABEL_LIKELY,
            "confidence": 1.0 - stats["p_value"],
            "input_tokens": len(ids),
            "device": self.device,
            "watermark": cfg.public_watermark(self.config),
        })
        return stats
