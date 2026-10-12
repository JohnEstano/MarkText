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
note says how to set it back. A version 2 file (no "models") is migrated
once more: the single model becomes the "models" catalog's default entry
and every other catalog model gets its own fresh key.

Since version 3 several open models can generate, each with its own
hashing key, so a score identifies which model made a text. The catalog
lives in "models" (short name -> model card); "default_model" names the
entry used when no model is chosen. The top-level "model_id" and the
watermark's key fields are always the default entry's view: every reader
(engine, scorer, classroom) keeps working unchanged, and config_for_model()
builds the same view for any other entry. To switch models, change
"default_model" or pick a model in the UI; do not edit the top-level
model_id or key fields by hand, the loader derives them from the catalog.

The hashing keys are the secrets in this file (one per model).
public_watermark(), public_models() and redacted() are the only ways
config data should leave the machine (sidecar files, reports, the About
page, the API). key_id is a random public label for a key, so a review
can say which key scored a text without revealing it.
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

CONFIG_VERSION = 3

# Open, ungated models a teacher can pick. Nothing here downloads until it
# is chosen: the engine loads (and Hugging Face fetches) one model at a
# time. Sizes are downloads, roughly; CPUs generate a few tokens a second
# on the small ones and crawl on the big ones.
MODEL_CATALOG = {
    "qwen05": {"model_id": "Qwen/Qwen2.5-0.5B-Instruct",
               "label": "Qwen2.5 0.5B", "approx_size": "about 1 GB"},
    "qwen15": {"model_id": "Qwen/Qwen2.5-1.5B-Instruct",
               "label": "Qwen2.5 1.5B", "approx_size": "about 3 GB"},
    "smol135": {"model_id": "HuggingFaceTB/SmolLM2-135M-Instruct",
                "label": "SmolLM2 135M", "approx_size": "about 270 MB"},
    "smol360": {"model_id": "HuggingFaceTB/SmolLM2-360M-Instruct",
                "label": "SmolLM2 360M", "approx_size": "about 700 MB"},
    "smol17": {"model_id": "HuggingFaceTB/SmolLM2-1.7B-Instruct",
               "label": "SmolLM2 1.7B", "approx_size": "about 3.4 GB"},
    "tinyllama": {"model_id": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
                  "label": "TinyLlama 1.1B Chat", "approx_size": "about 2.2 GB"},
}


def _blank_model_watermark():
    """Key material for one catalog entry; nulls are generated on load."""
    return {"hashing_key": None, "key_id": None, "retired_keys": []}


DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
    "default_model": "qwen05",
    "models": {name: {"model_id": card["model_id"], "label": card["label"],
                       "approx_size": card["approx_size"],
                       "watermark": _blank_model_watermark()}
               for name, card in MODEL_CATALOG.items()},
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


def _hide_key_material(wm):
    """Hide one watermark dict's secrets in place (retired keys keep ids)."""
    if "hashing_key" in wm:
        wm["hashing_key"] = "(hidden)"
    if wm.get("retired_keys"):
        wm["retired_keys"] = ["{} (hidden)".format(k.get("key_id")) for k in wm["retired_keys"]]


def redacted(config):
    """A copy of the config that is safe to display: every model's keys
    are hidden (retired keys are shown by their key id only)."""
    shown = copy.deepcopy(config)
    _hide_key_material(shown.get("watermark", {}))
    for entry in shown.get("models", {}).values():
        _hide_key_material(entry.get("watermark", {}))
    return shown


def public_models(config):
    """The model catalog as it may leave the machine: names, labels, sizes,
    model ids and key ids. Never the hashing keys."""
    return [{"name": name, "model_id": entry.get("model_id", ""),
             "label": entry.get("label", name),
             "approx_size": entry.get("approx_size", ""),
             "key_id": (entry.get("watermark") or {}).get("key_id")}
            for name, entry in config.get("models", {}).items()]


def model_names(config):
    """Short names of the models in the catalog, in file order."""
    return list(config.get("models", {}))


def default_model_name(config):
    """The default model's short name, or the first catalog entry."""
    name = config.get("default_model")
    if name in config.get("models", {}):
        return name
    names = model_names(config)
    return names[0] if names else ""


def model_entry(config, name):
    """One catalog entry, or ValueError naming the unknown model."""
    try:
        return config["models"][name]
    except (KeyError, TypeError):
        raise ValueError("Unknown model {!r}; choose one of: {}".format(
            name, ", ".join(model_names(config)))) from None


def model_label(config, name):
    """The dropdown text for a model: label, Hugging Face id and size."""
    entry = model_entry(config, name)
    return "{} ({}; {})".format(entry.get("label", name),
                                entry.get("model_id", "?"),
                                entry.get("approx_size", "?"))


def model_display_for_id(config, model_id):
    """The friendly label for a stored model id ("Qwen2.5 0.5B"), or the id
    itself when no catalog entry has it (old reviews, other installations)."""
    for entry in config.get("models", {}).values():
        if entry.get("model_id") and entry["model_id"] == model_id:
            return entry.get("label", model_id)
    return model_id or ""


def generated_by_text(config, label, model_id):
    """One plain line saying what a verdict means and, when flagged, which
    model made the text. "" when there is no score yet. (The label strings
    must match verdict.py; config cannot import it, verdict imports config.)"""
    model = model_display_for_id(config, model_id)
    if label == "LIKELY MARKTEXT":
        return "Likely generated by {}".format(model) if model else "Likely AI-generated"
    if label == "POSSIBLE WATERMARK":
        return "Possibly generated by {}".format(model) if model else "Possibly AI-generated"
    if label == "NOT DETECTED":
        return "No AI writing found"
    if label and label.startswith("INCONCLUSIVE"):
        return "Too short to check"
    return ""


def model_for_sidecar(config, generation):
    """Which catalog model a saved generation names: its "model" field,
    else the entry with the same model id, else the default. Old sidecars
    (no model, only a model id) still resolve when the id is known."""
    generation = generation or {}
    if generation.get("model") in config.get("models", {}):
        return generation["model"]
    for name, entry in config.get("models", {}).items():
        if entry.get("model_id") and entry["model_id"] == generation.get("model_id"):
            return name
    return default_model_name(config)


def config_for_model(config, name):
    """An engine-ready copy of the config for the named model: the top-level
    model id and key fields become that entry's (shared sampling settings
    stay). Raises ValueError for an unknown model."""
    entry = model_entry(config, name)
    chosen = copy.deepcopy(config)
    chosen["model_id"] = entry["model_id"]
    chosen["default_model"] = name
    entry_wm = entry.get("watermark") or {}
    chosen["watermark"].update(hashing_key=entry_wm.get("hashing_key"),
                               key_id=entry_wm.get("key_id"),
                               retired_keys=copy.deepcopy(entry_wm.get("retired_keys", [])))
    return chosen


def _resolve_default(config):
    """Point the top-level model id and key fields at the default entry, so
    every existing reader sees the default model without knowing about the
    catalog."""
    entry = model_entry(config, default_model_name(config))
    config["model_id"] = entry["model_id"]
    entry_wm = entry.get("watermark") or {}
    config["watermark"].update(hashing_key=entry_wm.get("hashing_key"),
                               key_id=entry_wm.get("key_id"),
                               retired_keys=copy.deepcopy(entry_wm.get("retired_keys", [])))
    return config


def _key_index(config):
    """(key_id, model name, retired?) for every key of every model."""
    found = []
    for name, entry in config.get("models", {}).items():
        wm = entry.get("watermark") or {}
        if wm.get("key_id") is not None:
            found.append((wm["key_id"], name, False))
        for old in wm.get("retired_keys", []):
            found.append((old.get("key_id"), name, True))
    return found


def config_for_key(config, key_id):
    """(model name, engine-ready config) scoring with the key labelled
    key_id (a current or retired key of any model), or None when no key
    has that label. Key ids are unique across models, so the pair also
    says which model made a text scored with it."""
    for found_id, name, _retired in _key_index(config):
        if found_id == key_id:
            chosen = config_for_model(config, name)
            if _retired:
                for old in chosen["watermark"]["retired_keys"]:
                    if old["key_id"] == key_id:
                        chosen["watermark"].update(hashing_key=old["hashing_key"],
                                                   key_id=old["key_id"])
                        break
            return name, chosen
    # files written before per-model keys: the top-level key still scores
    wm = config["watermark"]
    if key_id == wm.get("key_id"):
        return default_model_name(config), config
    for old in wm.get("retired_keys", []):
        if old["key_id"] == key_id:
            chosen = copy.deepcopy(config)
            chosen["watermark"].update(hashing_key=old["hashing_key"], key_id=old["key_id"])
            return default_model_name(config), chosen
    return None


def rotate_key(path=None, model=None):
    """Replace one model's hashing key with a new one, keeping the old key
    under that model's retired_keys: drafts made with it can then still be
    scored (the classroom scores a draft with the key its sidecar names).
    Default: the default model. Use it when a key may have leaked.
    Returns (old key id, new key id)."""
    path = pathlib.Path(path or CONFIG_PATH)
    config = load_config(path)
    name = model or default_model_name(config)
    entry_wm = model_entry(config, name).get("watermark")
    if entry_wm is None:
        raise ValueError("Model {!r} has no watermark key material.".format(name))
    old = {"hashing_key": entry_wm["hashing_key"], "key_id": entry_wm["key_id"]}
    taken_ids = {kid for kid, _n, _r in _key_index(config)}
    taken_keys = {k for _kid, k in _all_hashing_keys(config)}
    entry_wm["retired_keys"] = entry_wm.get("retired_keys", []) + [old]
    entry_wm["hashing_key"] = _fresh_key(taken_keys)
    entry_wm["key_id"] = _fresh_id(taken_ids)
    _resolve_default(config)
    validate_config(config)
    save_config(config, path)
    return old["key_id"], entry_wm["key_id"]


def _fresh_key(taken):
    key = new_hashing_key()
    while key in taken:
        key = new_hashing_key()
    return key


def _fresh_id(taken):
    kid = new_key_id()
    while kid in taken:
        kid = new_key_id()
    return kid


def _all_hashing_keys(config):
    """(key id or None, hashing key) for every model (retired keys have no
    reason to collide, but current keys must all differ so a score names
    one model)."""
    found = []
    for _name, entry in config.get("models", {}).items():
        wm = entry.get("watermark") or {}
        if wm.get("hashing_key") is not None:
            found.append((wm.get("key_id"), wm["hashing_key"]))
    return found


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

    models = config.get("models")
    need(isinstance(models, dict) and models, "models must be a non-empty object")
    need(isinstance(config.get("default_model"), str)
         and config["default_model"] in models,
         "default_model must name one of models ({})".format(", ".join(models) if isinstance(models, dict) else ""))
    seen_ids, seen_keys = [], []
    for name, entry in models.items():
        where = "models.{!r}".format(name)
        need(isinstance(entry, dict), "{0} must be an object".format(where))
        need(isinstance(entry.get("model_id"), str) and entry["model_id"],
             "{0}.model_id must be a non-empty string".format(where))
        for field in ("label", "approx_size"):
            need(isinstance(entry.get(field), str),
                 "{0}.{1} must be a string".format(where, field))
        ewm = entry.get("watermark")
        need(isinstance(ewm, dict), "{0}.watermark must be an object".format(where))
        ekey = ewm.get("hashing_key")
        need(ekey is None or (isinstance(ekey, int) and ekey > 0),
             "{0}.watermark.hashing_key must be a positive integer or null".format(where))
        ekid = ewm.get("key_id")
        need(ekid is None or (isinstance(ekid, str) and KEY_ID_PATTERN.fullmatch(ekid)),
             "{0}.watermark.key_id must be 8 lowercase hex characters or null".format(where))
        eretired = ewm.get("retired_keys")
        need(isinstance(eretired, list) and all(
            isinstance(k, dict) and isinstance(k.get("hashing_key"), int) and k["hashing_key"] > 0
            and isinstance(k.get("key_id"), str) and KEY_ID_PATTERN.fullmatch(k["key_id"])
            for k in eretired),
            "{0}.watermark.retired_keys must be a list of {{\"hashing_key\": positive integer, "
            "\"key_id\": 8 hex characters}}".format(where))
        for k in eretired + ([{"hashing_key": ekey, "key_id": ekid}] if ekid is not None else []):
            need(k["key_id"] not in seen_ids,
                 "{0}: key id {1} is already used by another key".format(where, k["key_id"]))
            seen_ids.append(k["key_id"])
        if ekey is not None:
            need(ekey not in seen_keys,
                 "{0}: two models must not share a hashing key, or a score cannot name "
                 "its model".format(where))
            seen_keys.append(ekey)
    # the top-level key fields are the default entry's view (see _resolve_default)
    first = models[config["default_model"]].get("watermark") or {}
    need(wm.get("hashing_key") == first.get("hashing_key")
         and wm.get("key_id") == first.get("key_id")
         and wm.get("retired_keys") == first.get("retired_keys", []),
         "the top-level watermark key fields must match models.{!r} (change default_model, "
         "not these fields)".format(config["default_model"]))

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


def _migrate_models(config):
    """Build the version 3 model catalog for a file that has none: every
    stock model gets an entry, the entry for the file's current model keeps
    its key (old texts still score), and every other entry gets a fresh
    private key, so each model watermarks differently. Returns the note
    describing what happened."""
    wm = config["watermark"]
    top_id = config["model_id"]
    catalog = {}
    taken_keys = {wm["hashing_key"]} if wm.get("hashing_key") is not None else set()
    taken_ids = {wm["key_id"]} if wm.get("key_id") is not None else set()
    for old in wm.get("retired_keys", []):
        taken_keys.add(old["hashing_key"])
        taken_ids.add(old["key_id"])
    default = None
    for name, card in MODEL_CATALOG.items():
        entry_wm = _blank_model_watermark()
        if card["model_id"] == top_id and default is None:
            entry_wm.update(hashing_key=wm.get("hashing_key"), key_id=wm.get("key_id"),
                            retired_keys=copy.deepcopy(wm.get("retired_keys", [])))
            default = name
        else:
            entry_wm.update(hashing_key=_fresh_key(taken_keys), key_id=_fresh_id(taken_ids))
            taken_keys.add(entry_wm["hashing_key"])
            taken_ids.add(entry_wm["key_id"])
        catalog[name] = {"model_id": card["model_id"], "label": card["label"],
                         "approx_size": card["approx_size"], "watermark": entry_wm}
    if default is None:
        catalog["custom"] = {"model_id": top_id, "label": "Custom",
                             "approx_size": "?",
                             "watermark": {"hashing_key": wm.get("hashing_key"),
                                           "key_id": wm.get("key_id"),
                                           "retired_keys": copy.deepcopy(
                                               wm.get("retired_keys", []))}}
        default = "custom"
    config["models"] = catalog
    config["default_model"] = default
    config["config_version"] = CONFIG_VERSION
    return ("The config was updated to version {}: generation can now pick from {} models "
            "({}), each with its own private watermark key, so a score names the model "
            "that made a text. The previous model and key became the '{}' entry, so old "
            "texts still score.".format(CONFIG_VERSION, len(catalog),
                                        ", ".join(model_label(config, n) for n in catalog),
                                        default))


def _fill_model_keys(config):
    """Generate a private key for every catalog entry still missing one.
    Returns True when anything was generated."""
    taken_keys = {k for _kid, k in _all_hashing_keys(config)}
    taken_ids = {kid for kid, _n, _r in _key_index(config)}
    made = False
    for entry in config.get("models", {}).values():
        ewm = entry.get("watermark") or {}
        if ewm.get("hashing_key") is None:
            ewm["hashing_key"] = _fresh_key(taken_keys)
            taken_keys.add(ewm["hashing_key"])
            made = True
        if ewm.get("key_id") is None:
            ewm["key_id"] = _fresh_id(taken_ids)
            taken_ids.add(ewm["key_id"])
            made = True
    return made


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
    if config.get("config_version", 1) < CONFIG_VERSION or "models" not in user:
        changed.append(_migrate_models(config))
    if _fill_model_keys(config):
        changed.append("One or more models had no watermark key; fresh private keys were "
                       "generated and saved (each model has its own, so a score names the "
                       "model that made the text).")
    _resolve_default(config)
    validate_config(config)
    if changed:
        save_config(config, path)
        notes.extend(changed)
    if wm["hashing_key"] == HF_PUBLIC_KEY:
        notes.append("The watermark key is Hugging Face's public default (15485863), so anyone "
                     "with transformers can fake or check your watermark. Run "
                     "`python -m classroom.cli rotate-key` for a private key; drafts made with "
                     "the old one still score.")
    return config


def create_config(path=None):
    """Write a fresh config with newly generated keys (one per model) and
    return it."""
    path = pathlib.Path(path or CONFIG_PATH)
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["watermark"]["hashing_key"] = new_hashing_key()
    config["watermark"]["key_id"] = new_key_id()
    _fill_model_keys(config)
    default = config["models"][config["default_model"]]["watermark"]
    default.update(hashing_key=config["watermark"]["hashing_key"],
                   key_id=config["watermark"]["key_id"], retired_keys=[])
    _resolve_default(config)
    save_config(config, path)
    return config


def save_config(config, path=None):
    path = pathlib.Path(path or CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
