"""Configuration management for MarkText.

Stores model selection, generation parameters, and watermark settings
in config/watermark_config.json. A fresh config is created from defaults
on first run.
"""

import json
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent

DEFAULT_CONFIG = {
    "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
    "device": "auto",
    "max_new_tokens": 300,
    "temperature": 0.8,
    "top_p": 0.9,
    "watermark": {
        "greenlist_ratio": 0.5,
        "bias": 3.0,
        "seeding_scheme": "selfhash",
        "context_width": 5,
        "hashing_key": 15485863,
    },
    "detection_threshold": 4.0,
}

CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "watermark_config.json"


def _deep_merge(base, override):
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path=None):
    path = pathlib.Path(path or CONFIG_PATH)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
            if isinstance(user, dict):
                return _deep_merge(DEFAULT_CONFIG, user)
        except (json.JSONDecodeError, OSError):
            pass
    return create_config(path)


def create_config(path=None):
    path = pathlib.Path(path or CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
    return dict(DEFAULT_CONFIG)


def save_config(config, path=None):
    path = pathlib.Path(path or CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
