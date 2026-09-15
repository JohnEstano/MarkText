"""MarkText generation and detection engine.

Wraps Hugging Face Qwen2.5 + WatermarkLogitsProcessor / WatermarkDetector
into a single, easy-to-use class for the GUI.
"""

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    WatermarkDetector,
    WatermarkingConfig,
)


def _resolve_device(preference):
    pref = str(preference).lower().strip()
    if pref == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if pref in ("cuda", "gpu"):
        return "cuda" if torch.cuda.is_available() else "cpu"
    return "cpu"


class Engine:
    def __init__(self, config, progress_callback=None):
        self.config = config
        self.device = _resolve_device(config.get("device", "auto"))

        if progress_callback:
            progress_callback("Loading tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(
            config["model_id"], trust_remote_code=True
        )

        if progress_callback:
            progress_callback("Loading model weights (may download on first run)...")
        dtype = torch.float16 if self.device == "cuda" else torch.bfloat16
        self.model = AutoModelForCausalLM.from_pretrained(
            config["model_id"],
            dtype=dtype,
            device_map=self.device if self.device == "cuda" else None,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        )
        if self.device == "cpu":
            self.model = self.model.to("cpu")
        self.model.eval()

        wm_cfg = config.get("watermark", {})
        self.watermark_config = WatermarkingConfig(
            greenlist_ratio=wm_cfg.get("greenlist_ratio", 0.5),
            bias=wm_cfg.get("bias", 3.0),
            seeding_scheme=wm_cfg.get("seeding_scheme", "selfhash"),
            context_width=wm_cfg.get("context_width", 5),
            hashing_key=wm_cfg.get("hashing_key", 15485863),
        )

        self.detector = WatermarkDetector(
            model_config=self.model.config,
            device=str(self.device),
            watermarking_config=self.watermark_config,
        )

        if progress_callback:
            progress_callback("Ready.")

    # ---------------------------------------------------------------- generate
    def generate(self, prompt, max_new_tokens=None, watermarked=True):
        if max_new_tokens is None:
            max_new_tokens = self.config.get("max_new_tokens", 300)

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
        )
        if watermarked:
            gen_kwargs["watermarking_config"] = self.watermark_config

        with torch.no_grad():
            output = self.model.generate(**inputs, **gen_kwargs)

        new_tokens = output[0][inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True)

    # ------------------------------------------------------------------ detect
    def detect(self, text):
        threshold = float(self.config.get("detection_threshold", 4.0))

        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)
        ids = inputs["input_ids"]

        if ids.shape[1] < 6:
            return None

        with torch.no_grad():
            result = self.detector(ids, z_threshold=threshold, return_dict=True)

        return {
            "num_tokens_scored": int(result.num_tokens_scored[0]),
            "num_green_tokens": int(result.num_green_tokens[0]),
            "green_fraction": float(result.green_fraction[0]),
            "z_score": float(result.z_score[0]),
            "prediction": bool(result.prediction[0]),
            "p_value": float(result.p_value[0]),
            "confidence": float(result.confidence[0]),
        }
