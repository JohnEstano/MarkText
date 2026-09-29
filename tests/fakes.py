"""A stand-in for engine.Engine: no torch, no model, instant answers.

Watermarked text is made of "wm" words and scores z = 6.0; any other text
scores z = -0.5. Texts under `min_tokens` words return None, as the real
Engine.detect does for texts too short to score.
"""

import copy

import config as cfg
import verdict


def fake_config(**classroom):
    c = copy.deepcopy(cfg.DEFAULT_CONFIG)
    c["model_id"] = "fake/model"
    c["watermark"].update(hashing_key=424242, key_id="0a1b2c3d")
    c["classroom"].update(classroom)
    return c


class FakeEngine:
    device = "cpu"
    min_tokens = 6

    def __init__(self, config=None, progress_callback=None):
        self.config = config or fake_config()
        self.generated, self.detected = [], []

    def reconfigure(self, config):
        if config["model_id"] != self.config["model_id"]:
            return False
        self.config = config
        return True

    def generate(self, prompt, max_new_tokens=None, watermarked=True, seed=None, cancel_event=None):
        n = int(max_new_tokens or self.config["max_new_tokens"])
        self.generated.append((prompt, n, watermarked))
        return {"text": " ".join(["wm" if watermarked else "nm"] * n),
                "mode": "watermarked" if watermarked else "normal",
                "watermarked": bool(watermarked),
                "cancelled": bool(cancel_event is not None and cancel_event.is_set()),
                "seed": 42 if seed is None else int(seed), "max_new_tokens": n,
                "new_tokens": n, "model_id": self.config["model_id"], "device": self.device,
                "temperature": 0.8, "top_p": 0.9, "top_k": 20, "repetition_penalty": 1.1,
                "watermark": cfg.public_watermark(self.config)}

    def detect(self, text):
        self.detected.append(text)
        words = text.split()
        if len(words) < self.min_tokens:
            return None
        scored = len(words) - 5
        marked = words[0] == "wm"
        z = 6.0 if marked else -0.5
        green = 0.7 if marked else 0.48
        return {"num_tokens_scored": scored, "num_green_tokens": int(scored * green),
                "green_fraction": green, "z_score": z, "prediction": marked,
                "p_value": 1e-9 if marked else 0.69, "confidence": 0.99,
                "label": verdict.classify(z, scored, self.config), "input_tokens": len(words),
                "device": self.device, "watermark": cfg.public_watermark(self.config)}
