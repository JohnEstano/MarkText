"""MarkText generation and detection engine.

Wraps Hugging Face Qwen2.5 and WatermarkingConfig for generation, and a
Scorer (scorer.py) for detection. Both are built from the same watermark
settings in the config, so generation and detection cannot disagree on
parameters; the scorer reuses the model's tokenizer and configuration.
"""

import random

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    StoppingCriteria,
    StoppingCriteriaList,
    WatermarkingConfig,
)

import config as cfg
from scorer import Scorer
# The labels and the threshold rule live in verdict.py (no torch); they are
# re-exported here so engine.LABEL_* and engine.classify keep working.
from verdict import (  # noqa: F401
    LABEL_INCONCLUSIVE,
    LABEL_LIKELY,
    LABEL_NOT_DETECTED,
    LABEL_POSSIBLE,
    LABELS,
    classify,
)


def _resolve_device(preference):
    pref = str(preference).lower().strip()
    if pref in ("auto", "cuda", "gpu"):
        return "cuda" if torch.cuda.is_available() else "cpu"
    if pref == "cpu":
        return "cpu"
    raise ValueError("Unknown device {!r}; use auto, cpu or cuda".format(preference))


class _CancelCriteria(StoppingCriteria):
    """Stops generation as soon as the shared event is set."""

    def __init__(self, event):
        self.event = event

    def __call__(self, input_ids, scores, **kwargs):
        return torch.full((input_ids.shape[0],), self.event.is_set(),
                          dtype=torch.bool, device=input_ids.device)


class Engine:
    def __init__(self, config, progress_callback=None):
        self.config = config
        self.device = _resolve_device(config.get("device", "auto"))

        if progress_callback:
            progress_callback("Loading tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(config["model_id"])

        if progress_callback:
            progress_callback("Loading model weights (may download on first run)...")
        dtype = torch.float16 if self.device == "cuda" else torch.bfloat16
        self.model = AutoModelForCausalLM.from_pretrained(
            config["model_id"],
            dtype=dtype,
            device_map=self.device if self.device == "cuda" else None,
            low_cpu_mem_usage=True,
        )
        if self.device == "cpu":
            self.model = self.model.to("cpu")
        self.model.eval()
        self._build_watermark()

        if progress_callback:
            progress_callback("Ready.")

    def _build_watermark(self):
        """The watermark settings, shared by generate() and the scorer."""
        wm_cfg = self.config["watermark"]
        self.watermark_config = WatermarkingConfig(
            greenlist_ratio=wm_cfg["greenlist_ratio"],
            bias=wm_cfg["bias"],
            seeding_scheme=wm_cfg["seeding_scheme"],
            context_width=wm_cfg["context_width"],
            hashing_key=wm_cfg["hashing_key"],
        )
        self.scorer = Scorer(self.config, self.tokenizer, self.model.config)
        # detection needs this many tokens before the first one can be scored
        self.min_tokens = self.scorer.min_tokens

    def reconfigure(self, config):
        """Adopt an edited config (a new key, other thresholds or sampling
        settings) without reloading the model. Returns False, changing
        nothing, when the model or the device changed: that needs a new
        Engine. The caller holds the engine's lock."""
        if (config["model_id"] != self.config["model_id"]
                or _resolve_device(config.get("device", "auto")) != self.device):
            return False
        self.config = config
        self._build_watermark()
        return True

    # ---------------------------------------------------------------- generate
    def generate(self, prompt, max_new_tokens=None, watermarked=True,
                 seed=None, cancel_event=None):
        """Generate a reply. Returns a dict with the text and everything
        needed to reproduce or explain it (seed, mode, parameters)."""
        if max_new_tokens is None:
            max_new_tokens = self.config.get("max_new_tokens", 300)
        if seed is None:
            seed = self.config.get("seed")
        if seed is None:
            seed = random.getrandbits(32)
        torch.manual_seed(seed)

        messages = [{"role": "user", "content": prompt}]
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)

        gen_kwargs = dict(
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=self.config.get("temperature", 0.8),
            top_p=self.config.get("top_p", 0.9),
            top_k=self.config.get("top_k", 20),
            repetition_penalty=self.config.get("repetition_penalty", 1.1),
        )
        if watermarked:
            gen_kwargs["watermarking_config"] = self.watermark_config
        if cancel_event is not None:
            gen_kwargs["stopping_criteria"] = StoppingCriteriaList(
                [_CancelCriteria(cancel_event)])

        with torch.no_grad():
            output = self.model.generate(**inputs, **gen_kwargs)

        new_tokens = output[0][inputs["input_ids"].shape[1]:]
        return {
            "text": self.tokenizer.decode(new_tokens, skip_special_tokens=True),
            "mode": "watermarked" if watermarked else "normal",
            "watermarked": bool(watermarked),
            "cancelled": bool(cancel_event is not None and cancel_event.is_set()),
            "seed": int(seed),
            "max_new_tokens": int(max_new_tokens),
            "new_tokens": int(new_tokens.shape[0]),
            "model_id": self.config["model_id"],
            "device": self.device,
            "temperature": gen_kwargs["temperature"],
            "top_p": gen_kwargs["top_p"],
            "top_k": gen_kwargs["top_k"],
            "repetition_penalty": gen_kwargs["repetition_penalty"],
            # never the hashing key: this dict ends up in sidecar files
            "watermark": cfg.public_watermark(self.config),
        }

    # ------------------------------------------------------------------ detect
    def detect(self, text):
        """Score a text. Returns None when it is too short to score at all,
        otherwise a dict of statistics plus the verdict `label` (see
        scorer.py for every step)."""
        return self.scorer.detect(text)
