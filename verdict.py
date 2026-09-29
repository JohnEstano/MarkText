"""The four verdict labels and the rule that picks one.

Pure Python (no torch), so the history, the experiment and the classroom
can name a verdict without loading the model. engine.py re-exports these
names, so `engine.LABEL_LIKELY` and `engine.classify` keep working.
"""

import config as cfg

LABEL_LIKELY = "LIKELY MARKTEXT"
LABEL_POSSIBLE = "POSSIBLE WATERMARK"
LABEL_NOT_DETECTED = "NOT DETECTED"
LABEL_INCONCLUSIVE = "INCONCLUSIVE (short text)"
LABELS = (LABEL_LIKELY, LABEL_POSSIBLE, LABEL_NOT_DETECTED, LABEL_INCONCLUSIVE)


def classify(z, tokens_scored, config):
    """Verdict label for a z-score. All thresholds come from the config."""
    if tokens_scored < int(config.get("min_tokens_for_verdict", 0)):
        return LABEL_INCONCLUSIVE
    if z >= float(config.get("detection_threshold", 4.0)):
        return LABEL_LIKELY
    if z >= float(config.get("possible_threshold", 2.0)):
        return LABEL_POSSIBLE
    return LABEL_NOT_DETECTED


def placeholder_stats(config, device):
    """Stats for a text too short to score at all (Engine.detect returned
    None). Logged as INCONCLUSIVE so the attempt is still on record."""
    return {"num_tokens_scored": 0, "num_green_tokens": 0, "green_fraction": 0.0,
            "z_score": 0.0, "p_value": 1.0, "label": LABEL_INCONCLUSIVE,
            "device": device, "watermark": cfg.public_watermark(config)}
