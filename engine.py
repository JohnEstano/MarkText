"""MarkText generation and detection engine.

Wraps Hugging Face Qwen2.5 + WatermarkingConfig / WatermarkDetector into
one class. The same WatermarkingConfig object is handed to generate() and
to the detector, so generation and detection cannot disagree on parameters.
The engine is also the only place that turns a z-score into a verdict.
"""

import random

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    StoppingCriteria,
    StoppingCriteriaList,
    WatermarkDetector,
    WatermarkingConfig,
)

LABEL_LIKELY = "LIKELY MARKTEXT"
LABEL_POSSIBLE = "POSSIBLE WATERMARK"
LABEL_NOT_DETECTED = "NOT DETECTED"
LABEL_INCONCLUSIVE = "INCONCLUSIVE (short text)"
LABELS = (LABEL_LIKELY, LABEL_POSSIBLE, LABEL_NOT_DETECTED, LABEL_INCONCLUSIVE)


def _resolve_device(preference):
    pref = str(preference).lower().strip()
    if pref in ("auto", "cuda", "gpu"):
        return "cuda" if torch.cuda.is_available() else "cpu"
    if pref == "cpu":
        return "cpu"
    raise ValueError("Unknown device {!r}; use auto, cpu or cuda".format(preference))


def classify(z, tokens_scored, config):
    """Verdict label for a z-score. All thresholds come from the config."""
    if tokens_scored < int(config.get("min_tokens_for_verdict", 0)):
        return LABEL_INCONCLUSIVE
    if z >= float(config.get("detection_threshold", 4.0)):
        return LABEL_LIKELY
    if z >= float(config.get("possible_threshold", 2.0)):
        return LABEL_POSSIBLE
    return LABEL_NOT_DETECTED


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
        wm_cfg = config["watermark"]
        # detection needs this many tokens before the first one can be scored
        self.min_tokens = int(wm_cfg["context_width"]) + 1

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

        self.watermark_config = WatermarkingConfig(
            greenlist_ratio=wm_cfg["greenlist_ratio"],
            bias=wm_cfg["bias"],
            seeding_scheme=wm_cfg["seeding_scheme"],
            context_width=wm_cfg["context_width"],
            hashing_key=wm_cfg["hashing_key"],
        )

        self.detector = WatermarkDetector(
            model_config=self.model.config,
            device=str(self.device),
            watermarking_config=self.watermark_config,
            ignore_repeated_ngrams=bool(wm_cfg.get("ignore_repeated_ngrams", False)),
        )

        if progress_callback:
            progress_callback("Ready.")

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
        wm = self.config["watermark"]
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
            "watermark": {
                "greenlist_ratio": wm["greenlist_ratio"],
                "bias": wm["bias"],
                "seeding_scheme": wm["seeding_scheme"],
                "context_width": wm["context_width"],
                "hashing_key": wm["hashing_key"],
            },
        }

    # ------------------------------------------------------------------ detect
    def detect(self, text):
        """Score a text. Returns None when it is too short to score at all,
        otherwise a dict of statistics plus the verdict `label`."""
        threshold = float(self.config.get("detection_threshold", 4.0))

        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)
        ids = inputs["input_ids"]

        if ids.shape[1] < self.min_tokens:
            return None

        with torch.no_grad():
            result = self.detector(ids, z_threshold=threshold, return_dict=True)

        tokens_scored = int(result.num_tokens_scored[0])
        z = float(result.z_score[0])
        return {
            "num_tokens_scored": tokens_scored,
            "num_green_tokens": int(result.num_green_tokens[0]),
            "green_fraction": float(result.green_fraction[0]),
            "z_score": z,
            "prediction": bool(result.prediction[0]),
            "p_value": float(result.p_value[0]),
            "confidence": float(result.confidence[0]),
            "label": classify(z, tokens_scored, self.config),
        }
