import os
import pathlib
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["MARKTEXT_SKIP_MODEL"] = "1"

import history                      # noqa: E402
import experiment                   # noqa: E402
from api import main as api_main    # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

WM = {"bias": 3.0, "greenlist_ratio": 0.5, "seeding_scheme": "selfhash", "context_width": 5}


class FakeEngine:
    device = "cpu"
    min_tokens = 6

    def __init__(self, config):
        self.config = config

    def generate(self, prompt, max_new_tokens=None, watermarked=True, seed=None, cancel_event=None):
        return {"text": ("wm " if watermarked else "nm ") * max_new_tokens,
                "mode": "watermarked" if watermarked else "normal", "watermarked": watermarked,
                "cancelled": False, "seed": seed if seed is not None else 42,
                "max_new_tokens": max_new_tokens, "new_tokens": max_new_tokens,
                "model_id": "fake", "device": "cpu", "temperature": 0.8, "top_p": 0.9,
                "top_k": 20, "repetition_penalty": 1.1, "watermark": dict(WM, hashing_key=1)}

    def detect(self, text):
        n = len(text.split())
        if n < self.min_tokens:
            return None
        z = 6.5 if text.startswith("wm") else -0.4
        label = ("INCONCLUSIVE (short text)" if n < 100
                 else "LIKELY MARKTEXT" if z >= 4 else "NOT DETECTED")
        return {"num_tokens_scored": n - 4, "num_green_tokens": int(n * 0.7), "green_fraction": 0.7,
                "z_score": z, "prediction": z > 4, "p_value": 1e-9 if z > 4 else 0.6,
                "confidence": 0.9, "label": label, "input_tokens": n, "device": "cpu",
                "watermark": WM}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "logs" / "h.csv")
    monkeypatch.setattr(history, "EXPORT_DIR", tmp_path / "logs" / "exports")
    monkeypatch.setattr(experiment, "EXPORT_DIR", tmp_path / "logs" / "exports")
    monkeypatch.setattr(api_main, "GENERATED_DIR", tmp_path / "generated")
    pf = tmp_path / "prompts.txt"
    pf.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    monkeypatch.setattr(experiment, "PROMPT_FILE", pf)
    with TestClient(api_main.app) as c:
        api_main.state["engine"] = FakeEngine(api_main.state["config"])
        api_main.state["lock"] = threading.Lock()
        yield c
