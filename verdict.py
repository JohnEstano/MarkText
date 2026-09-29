"""The four verdict labels and the rule that picks one.

Pure Python (no torch), so the history, the experiment and the classroom
can name a verdict without loading the model. engine.py re-exports these
names, so `engine.LABEL_LIKELY` and `engine.classify` keep working.
"""

import math

import config as cfg

LABEL_LIKELY = "LIKELY MARKTEXT"
LABEL_POSSIBLE = "POSSIBLE WATERMARK"
LABEL_NOT_DETECTED = "NOT DETECTED"
LABEL_INCONCLUSIVE = "INCONCLUSIVE (short text)"
LABELS = (LABEL_LIKELY, LABEL_POSSIBLE, LABEL_NOT_DETECTED, LABEL_INCONCLUSIVE)

# the passage scan in scorer.py: windows of this many scored tokens, one
# every PASSAGE_STEP tokens (chosen by simulation; see scorer.py)
PASSAGE_WINDOW = 150
PASSAGE_STEP = 50


def normal_tail(z):
    """P(Z >= z) for a standard normal Z: the one-sided p-value of a z-score.
    math.erfc keeps its precision far into the tail (z = 8 gives 6.2e-16)."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def classify(z, tokens_scored, config):
    """Verdict label for a z-score. All thresholds come from the config."""
    if tokens_scored < int(config.get("min_tokens_for_verdict", 0)):
        return LABEL_INCONCLUSIVE
    if z >= float(config.get("detection_threshold", 4.0)):
        return LABEL_LIKELY
    if z >= float(config.get("possible_threshold", 2.0)):
        return LABEL_POSSIBLE
    return LABEL_NOT_DETECTED


def likely_p(config):
    """The p-value of the "likely" threshold: 3.2e-5 for z = 4.0."""
    return normal_tail(float(config.get("detection_threshold", 4.0)))


def placeholder_stats(config, device):
    """Stats for a text too short to score at all (Engine.detect returned
    None). Logged as INCONCLUSIVE so the attempt is still on record."""
    return {"num_tokens_scored": 0, "num_green_tokens": 0, "green_fraction": 0.0,
            "z_score": 0.0, "p_value": 1.0, "repeated": 0, "passage": None,
            "label": LABEL_INCONCLUSIVE, "device": device, "watermark": cfg.public_watermark(config)}
