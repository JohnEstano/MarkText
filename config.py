"""Configuration management for MarkText.

Stores model selection, generation parameters, and watermark settings
in config/watermark_config.json. A fresh config is created from defaults
on first run, with a newly generated private hashing key.

load_config() merges the file over DEFAULT_CONFIG, validates the result,
and can report what it had to do (generate a key, add a key id, warn about
the public default key) through an optional `notes` list.

A file that exists but cannot be read (a typo in the JSON, a wrong value)
stops the program with a ValueError that names the problem. It is never
replaced: a replacement would carry a new hashing key, and every text
watermarked with the old key would silently stop being detected.

config_version marks the file's layout. A version 1 file (no
config_version) is migrated once: repeated n-grams are then counted once
(ignore_repeated_ngrams true), because version 1 files carry the old
default, false, written by this loader rather than chosen by a person; the
note says how to set it back.

The hashing key is the one secret in this file. public_watermark() and
redacted() are the only ways config data should leave the machine (sidecar
files, reports, the About page). key_id is a random public label for the
current key, so a review can say which key scored it without revealing it.
"""

import copy
import json
import pathlib
import re
import secrets

BASE_DIR = pathlib.Path(__file__).resolve().parent

# Hugging Face's own default key. Anyone with transformers can generate or
# verify text made with it, so it is flagged when found in a config.
HF_PUBLIC_KEY = 15485863

CONFIG_VERSION = 2

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
    "device": "auto",
    "max_new_tokens": 300,
    "temperature": 0.8,
    "top_p": 0.9,
    # Qwen ships these in its own generation_config.json; listed here so the
    # JSON file fully describes how text is sampled.
    "top_k": 20,
    "repetition_penalty": 1.1,
    "seed": None,
    "watermark": {
        "greenlist_ratio": 0.5,
        "bias": 3.0,
        "seeding_scheme": "selfhash",
        "context_width": 5,
        "hashing_key": None,
        # random public label of the key above; regenerated with the key
        "key_id": None,
        # keys replaced by rotate_key(), kept so drafts made with them can
        # still be scored: [{"hashing_key": ..., "key_id": ...}]
        "retired_keys": [],
        # count a repeated (context, token) n-gram once: a second copy of a
        # phrase is not new evidence (scorer.py, arXiv:2306.04634)
        "ignore_repeated_ngrams": True,
    },
    "detection_threshold": 4.0,
    "possible_threshold": 2.0,
    "min_tokens_for_verdict": 100,
    # the classroom system (classroom/ package, app_pages/)
    "classroom": {
        # the student's "Draft with the assistant" box; false hides it
        "assistant_enabled": True,
        "assistant_max_tokens": 300,
        # sign a browser tab out after this many idle minutes (0 = never)
        "idle_minutes": 30,
        # backup copies kept per data file in data/backups/ (the newest ones)
        "keep_backups": 30,
    },
}

CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "watermark_config.json"

VALID_DEVICES = ("auto", "cpu", "cuda", "gpu")
VALID_SCHEMES = ("selfhash", "lefthash")

# watermark fields a reader needs to interpret a score; never the key
PUBLIC_WATERMARK_KEYS = ("greenlist_ratio", "bias", "seeding_scheme", "context_width", "key_id")
KEY_ID_PATTERN = re.compile(r"[0-9a-f]{8}")


def _deep_merge(base, override):
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def new_hashing_key():
    """A random 31-bit key, the same size as the public default."""
    return secrets.randbits(31) | 1


def new_key_id():
    """A random public label for a key. Deliberately not derived from the
    key: a 31-bit key could be recovered from any hash of it by trying all
    two billion values."""
    return secrets.token_hex(4)


def public_watermark(config):
    """The watermark parameters that may be written to files or shown."""
    wm = config["watermark"]
    return {k: wm.get(k) for k in PUBLIC_WATERMARK_KEYS}


def redacted(config):
    """A copy of the config that is safe to display: the keys are hidden
    (retired keys are shown by their key id only)."""
    shown = copy.deepcopy(config)
    wm = shown.get("watermark", {})
    if "hashing_key" in wm:
        wm["hashing_key"] = "(hidden)"
    if wm.get("retired_keys"):
        wm["retired_keys"] = ["{} (hidden)".format(k.get("key_id")) for k in wm["retired_keys"]]
    return shown


def config_for_key(config, key_id):
    """A copy of the config that scores with the key labelled key_id (the
    current one or a retired one), or None when no key has that label."""
    wm = config["watermark"]
    if key_id == wm.get("key_id"):
        return config
    for old in wm.get("retired_keys", []):
        if old["key_id"] == key_id:
            chosen = copy.deepcopy(config)
            chosen["watermark"].update(hashing_key=old["hashing_key"], key_id=old["key_id"])
            return chosen
    return None


def rotate_key(path=None):
    """Replace the hashing key with a new one, keeping the old key under
    retired_keys: drafts made with it can then still be scored (the
    classroom scores a draft with the key its sidecar names). Use it when
    the key may have leaked. Returns (old key id, new key id)."""
    path = pathlib.Path(path or CONFIG_PATH)
    config = load_config(path)
    wm = config["watermark"]
    old = {"hashing_key": wm["hashing_key"], "key_id": wm["key_id"]}
    wm["retired_keys"] = wm.get("retired_keys", []) + [old]
    wm["hashing_key"] = new_hashing_key()
    wm["key_id"] = new_key_id()
    while wm["key_id"] in {k["key_id"] for k in wm["retired_keys"]}:
        wm["key_id"] = new_key_id()
    validate_config(config)
    save_config(config, path)
    return old["key_id"], wm["key_id"]


def validate_config(config):
    """Raise ValueError with a specific message for any bad value."""
    def need(cond, msg):
        if not cond:
            raise ValueError("watermark_config.json: " + msg)

    need(isinstance(config.get("config_version"), int) and not isinstance(config["config_version"], bool)
         and 1 <= config["config_version"] <= CONFIG_VERSION,
         "config_version must be an integer from 1 to {}".format(CONFIG_VERSION))
    need(isinstance(config.get("model_id"), str) and config["model_id"],
         "model_id must be a non-empty string")
    need(str(config.get("device", "")).lower() in VALID_DEVICES,
         "device must be one of {}".format(", ".join(VALID_DEVICES)))
    need(isinstance(config.get("max_new_tokens"), int) and config["max_new_tokens"] > 0,
         "max_new_tokens must be a positive integer")
    need(config.get("temperature", 0) > 0, "temperature must be > 0")
    need(0 < config.get("top_p", 0) <= 1, "top_p must be in (0, 1]")
    need(isinstance(config.get("top_k"), int) and config["top_k"] >= 0,
         "top_k must be a non-negative integer")
    need(config.get("repetition_penalty", 0) > 0, "repetition_penalty must be > 0")
    seed = config.get("seed")
    need(seed is None or isinstance(seed, int), "seed must be an integer or null")

    wm = config.get("watermark")
    need(isinstance(wm, dict), "watermark must be an object")
    need(0 < wm.get("greenlist_ratio", 0) < 1, "watermark.greenlist_ratio must be in (0, 1)")
    need(wm.get("bias", -1) >= 0, "watermark.bias must be >= 0")
    need(wm.get("seeding_scheme") in VALID_SCHEMES,
         "watermark.seeding_scheme must be selfhash or lefthash")
    need(isinstance(wm.get("context_width"), int) and wm["context_width"] >= 1,
         "watermark.context_width must be an integer >= 1")
    key = wm.get("hashing_key")
    need(key is None or (isinstance(key, int) and key > 0),
         "watermark.hashing_key must be a positive integer or null")
    key_id = wm.get("key_id")
    need(key_id is None or (isinstance(key_id, str) and KEY_ID_PATTERN.fullmatch(key_id)),
         "watermark.key_id must be 8 lowercase hex characters or null")
    need(isinstance(wm.get("ignore_repeated_ngrams"), bool),
         "watermark.ignore_repeated_ngrams must be true or false")
    retired = wm.get("retired_keys")
    need(isinstance(retired, list) and all(
        isinstance(k, dict) and isinstance(k.get("hashing_key"), int) and k["hashing_key"] > 0
        and isinstance(k.get("key_id"), str) and KEY_ID_PATTERN.fullmatch(k["key_id"]) for k in retired),
        "watermark.retired_keys must be a list of {\"hashing_key\": positive integer, "
        "\"key_id\": 8 hex characters}")
    ids = [k["key_id"] for k in retired] + [key_id]
    need(len(ids) == len(set(ids)), "watermark key ids must all be different")

    need(config.get("possible_threshold", 0) > 0, "possible_threshold must be > 0")
    need(config.get("detection_threshold", 0) > config["possible_threshold"],
         "detection_threshold must be greater than possible_threshold")
    need(isinstance(config.get("min_tokens_for_verdict"), int)
         and config["min_tokens_for_verdict"] >= 0,
         "min_tokens_for_verdict must be a non-negative integer")

    room = config.get("classroom")
    need(isinstance(room, dict), "classroom must be an object")
    need(isinstance(room.get("assistant_enabled"), bool),
         "classroom.assistant_enabled must be true or false")
    tokens = room.get("assistant_max_tokens")
    need(isinstance(tokens, int) and not isinstance(tokens, bool) and 50 <= tokens <= 2000,
         "classroom.assistant_max_tokens must be an integer from 50 to 2000")
    idle = room.get("idle_minutes")
    need(isinstance(idle, int) and not isinstance(idle, bool) and 0 <= idle <= 1440,
         "classroom.idle_minutes must be an integer from 0 (never) to 1440")
    keep = room.get("keep_backups")
    need(isinstance(keep, int) and not isinstance(keep, bool) and 3 <= keep <= 1000,
         "classroom.keep_backups must be an integer from 3 to 1000")


def load_config(path=None, notes=None):
    """Return the validated config. `notes` (a list) collects messages about
    anything the loader had to do; front-ends show them to the user."""
    path = pathlib.Path(path or CONFIG_PATH)
    notes = notes if notes is not None else []
    if not path.exists():
        config = create_config(path)
        notes.append("Config created at {} with a new private hashing key.".format(path))
        return config
    try:
        # utf-8-sig: Notepad may save the file with a byte-order mark
        with open(path, "r", encoding="utf-8-sig") as f:
            user = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(
            "{} is not valid JSON ({}). Nothing was changed. Fix the file (compare it with "
            "watermark_config.example.json). Do not delete it unless you accept a new hashing key: "
            "texts watermarked with the current key would no longer be detected.".format(
                path.name, exc)) from exc
    except OSError as exc:
        raise ValueError("{} could not be read ({}).".format(path.name, exc)) from exc
    if not isinstance(user, dict):
        raise ValueError("{} should hold a JSON object at the top level.".format(path.name))

    config = _deep_merge(DEFAULT_CONFIG, user)
    wm = config["watermark"]
    changed = []
    if "config_version" not in user:
        # version 1: its false was the loader's old default, written out on save
        wm["ignore_repeated_ngrams"] = True
        config["config_version"] = CONFIG_VERSION
        changed.append("The config was updated to version {}: a phrase repeated in a text now "
                       "counts once when scoring (watermark.ignore_repeated_ngrams: true), because "
                       "counting repeats inflates z on human text. Set it to false to count every "
                       "repeat as before.".format(CONFIG_VERSION))
    if wm.get("hashing_key") is None:
        wm["hashing_key"] = new_hashing_key()
        wm["key_id"] = new_key_id()
        changed.append("No hashing key in the config; a new private key was generated and saved.")
    elif wm.get("key_id") is None:
        wm["key_id"] = new_key_id()
        changed.append("The hashing key had no key id; one was added and saved "
                       "(reviews use it to say which key scored a text).")
    validate_config(config)
    if changed:
        save_config(config, path)
        notes.extend(changed)
    if wm["hashing_key"] == HF_PUBLIC_KEY:
        notes.append("The hashing key is Hugging Face's public default (15485863): "
                     "anyone with transformers can produce or verify this watermark. "
                     "Delete config/watermark_config.json to get a private key "
                     "(old texts will then no longer be detectable).")
    return config


def create_config(path=None):
    """Write a fresh config with a newly generated key and return it."""
    path = pathlib.Path(path or CONFIG_PATH)
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["watermark"]["hashing_key"] = new_hashing_key()
    config["watermark"]["key_id"] = new_key_id()
    save_config(config, path)
    return config


def save_config(config, path=None):
    path = pathlib.Path(path or CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
