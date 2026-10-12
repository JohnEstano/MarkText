import copy
import json

import pytest

import config as cfg


def good():
    c = copy.deepcopy(cfg.DEFAULT_CONFIG)
    c["watermark"]["hashing_key"] = 12345
    c["models"]["qwen05"]["watermark"]["hashing_key"] = 12345   # top level mirrors it
    return c


def test_deep_merge_keeps_defaults_and_nests():
    merged = cfg._deep_merge(cfg.DEFAULT_CONFIG, {"device": "cpu", "watermark": {"bias": 1.5}})
    assert merged["device"] == "cpu"
    assert merged["watermark"]["bias"] == 1.5
    assert merged["watermark"]["greenlist_ratio"] == 0.5      # untouched sibling kept
    assert merged["max_new_tokens"] == 300


def test_deep_merge_does_not_alias_defaults():
    merged = cfg._deep_merge(cfg.DEFAULT_CONFIG, {})
    merged["watermark"]["bias"] = 99
    assert cfg.DEFAULT_CONFIG["watermark"]["bias"] == 3.0


def test_validate_accepts_defaults_with_key():
    cfg.validate_config(good())


@pytest.mark.parametrize("path, value", [
    (("device",), "mps"),
    (("watermark", "greenlist_ratio"), 1.0),
    (("watermark", "seeding_scheme"), "hash"),
    (("watermark", "context_width"), 0),
    (("possible_threshold",), 5.0),          # >= detection_threshold
    (("max_new_tokens",), -1),
    (("watermark", "hashing_key"), "abc"),
    (("watermark", "key_id"), "NOT-HEX!"),
    (("classroom", "assistant_enabled"), "yes"),
    (("classroom", "assistant_max_tokens"), 10),
    (("classroom", "assistant_max_tokens"), True),
])
def test_validate_rejects_bad_values(path, value):
    c = good()
    node = c
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    with pytest.raises(ValueError):
        cfg.validate_config(c)


def test_missing_file_is_created_with_private_key(tmp_path):
    path = tmp_path / "wm.json"
    notes = []
    c = cfg.load_config(path, notes)
    assert path.exists()
    key = c["watermark"]["hashing_key"]
    assert isinstance(key, int) and key > 0 and key != cfg.HF_PUBLIC_KEY
    assert json.loads(path.read_text(encoding="utf-8"))["watermark"]["hashing_key"] == key
    assert any("new private hashing key" in n for n in notes)


def test_null_key_is_generated_and_saved(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text(json.dumps({"watermark": {"hashing_key": None}}), encoding="utf-8")
    notes = []
    c = cfg.load_config(path, notes)
    assert c["watermark"]["hashing_key"] != cfg.HF_PUBLIC_KEY
    assert json.loads(path.read_text(encoding="utf-8"))["watermark"]["hashing_key"] == \
        c["watermark"]["hashing_key"]
    assert any("generated" in n for n in notes)


def test_public_default_key_is_kept_but_flagged(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text(json.dumps({"watermark": {"hashing_key": cfg.HF_PUBLIC_KEY}}), encoding="utf-8")
    notes = []
    c = cfg.load_config(path, notes)
    assert c["watermark"]["hashing_key"] == cfg.HF_PUBLIC_KEY
    note = next(n for n in notes if "public default" in n)
    # the way out keeps the old key, so drafts made with it still score
    assert "python -m classroom.cli rotate-key" in note and "Delete" not in note
    old, _ = cfg.rotate_key(path)
    notes = []
    c = cfg.load_config(path, notes)
    assert not any("public default" in n for n in notes)
    assert c["watermark"]["retired_keys"] == [{"hashing_key": cfg.HF_PUBLIC_KEY, "key_id": old}]


def test_a_broken_file_stops_and_is_left_alone(tmp_path):
    # a typo must never cost the key: a new file would carry a new key and
    # every earlier watermarked text would stop being detected
    path = tmp_path / "wm.json"
    path.write_text('{"watermark": {"hashing_key": 123457,}}', encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        cfg.load_config(path)
    assert path.read_text(encoding="utf-8") == '{"watermark": {"hashing_key": 123457,}}'
    assert list(tmp_path.iterdir()) == [path]


def test_a_top_level_that_is_not_an_object_stops(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        cfg.load_config(path)


def test_a_byte_order_mark_is_accepted(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text(json.dumps({"watermark": {"hashing_key": 123457, "key_id": "0a1b2c3d"}}),
                    encoding="utf-8-sig")
    assert cfg.load_config(path)["watermark"]["hashing_key"] == 123457


def test_partial_file_gets_defaults(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text(json.dumps({"device": "cpu", "watermark": {"hashing_key": 7}}), encoding="utf-8")
    c = cfg.load_config(path, [])
    assert c["device"] == "cpu"
    assert c["watermark"]["hashing_key"] == 7
    assert c["top_k"] == 20
    assert c["min_tokens_for_verdict"] == 100


def test_classroom_defaults_are_merged_into_old_files(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text(json.dumps({"watermark": {"hashing_key": 7}}), encoding="utf-8")
    c = cfg.load_config(path, [])
    assert c["classroom"] == {"assistant_enabled": True, "assistant_max_tokens": 300, "idle_minutes": 30,
                              "keep_backups": 30}


def test_new_config_gets_a_key_id(tmp_path):
    c = cfg.load_config(tmp_path / "wm.json", [])
    assert cfg.KEY_ID_PATTERN.fullmatch(c["watermark"]["key_id"])


def test_key_id_is_added_to_an_existing_key_and_saved(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text(json.dumps({"watermark": {"hashing_key": 7}}), encoding="utf-8")
    notes = []
    c = cfg.load_config(path, notes)
    key_id = c["watermark"]["key_id"]
    assert cfg.KEY_ID_PATTERN.fullmatch(key_id)
    assert json.loads(path.read_text(encoding="utf-8"))["watermark"]["key_id"] == key_id
    assert any("no watermark key" in n for n in notes)
    assert cfg.load_config(path, [])["watermark"]["key_id"] == key_id     # stable afterwards


def test_key_id_is_not_derived_from_the_key(tmp_path):
    ids = set()
    for name in ("a.json", "b.json"):
        path = tmp_path / name
        path.write_text(json.dumps({"watermark": {"hashing_key": 7}}), encoding="utf-8")
        ids.add(cfg.load_config(path, [])["watermark"]["key_id"])
    assert len(ids) == 2                      # same key, different labels


def test_public_watermark_and_redacted_never_show_the_key():
    c = good()
    c["watermark"]["key_id"] = "0a1b2c3d"
    pub = cfg.public_watermark(c)
    assert "hashing_key" not in pub and pub["key_id"] == "0a1b2c3d"
    assert set(pub) == set(cfg.PUBLIC_WATERMARK_KEYS)
    shown = cfg.redacted(c)
    assert shown["watermark"]["hashing_key"] == "(hidden)"
    assert c["watermark"]["hashing_key"] == 12345                 # original untouched


def test_a_version_1_file_is_migrated_to_count_repeats_once(tmp_path):
    path = tmp_path / "wm.json"
    old = good()
    del old["config_version"]
    old["watermark"]["ignore_repeated_ngrams"] = False          # what the old loader wrote
    path.write_text(json.dumps(old), encoding="utf-8")
    notes = []
    c = cfg.load_config(path, notes)
    assert c["config_version"] == 3 and c["watermark"]["ignore_repeated_ngrams"] is True
    assert any("counts once" in n for n in notes)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["config_version"] == 3 and saved["watermark"]["hashing_key"] == 12345


def test_a_version_2_choice_is_kept(tmp_path):
    path = tmp_path / "wm.json"
    new = good()
    new["watermark"]["ignore_repeated_ngrams"] = False
    path.write_text(json.dumps(new), encoding="utf-8")
    notes = []
    assert cfg.load_config(path, notes)["watermark"]["ignore_repeated_ngrams"] is False
    assert not any("counts once" in n for n in notes)


def test_the_example_file_is_current():
    example = json.loads((cfg.BASE_DIR / "config" / "watermark_config.example.json").read_text(encoding="utf-8"))
    assert example["config_version"] == cfg.CONFIG_VERSION
    assert set(example) == set(cfg.DEFAULT_CONFIG)
    assert set(example["watermark"]) == set(cfg.DEFAULT_CONFIG["watermark"])
    assert set(example["models"]) == set(cfg.DEFAULT_CONFIG["models"])
    first = next(iter(example["models"].values()))
    assert set(first) == {"model_id", "label", "approx_size", "watermark"}
    assert set(first["watermark"]) == {"hashing_key", "key_id", "retired_keys"}


def test_rotating_the_key_keeps_the_old_one(tmp_path):
    path = tmp_path / "wm.json"
    first = cfg.load_config(path)
    old, new = cfg.rotate_key(path)
    now = cfg.load_config(path)
    assert old == first["watermark"]["key_id"] and new == now["watermark"]["key_id"] != old
    assert now["watermark"]["retired_keys"] == [{"hashing_key": first["watermark"]["hashing_key"],
                                                 "key_id": old}]
    name, scored = cfg.config_for_key(now, old)
    assert name == cfg.default_model_name(now)
    assert scored["watermark"]["hashing_key"] == first["watermark"]["hashing_key"]
    name, scored = cfg.config_for_key(now, new)
    assert name == cfg.default_model_name(now) and scored["watermark"]["key_id"] == new
    assert cfg.config_for_key(now, "ffffffff") is None
    shown = json.dumps(cfg.redacted(now))
    assert str(first["watermark"]["hashing_key"]) not in shown and old in shown


def test_retired_keys_are_validated():
    c = good()
    c["watermark"]["key_id"] = "0a1b2c3d"
    c["watermark"]["retired_keys"] = [{"hashing_key": 99, "key_id": "0a1b2c3d"}]
    with pytest.raises(ValueError, match="different"):
        cfg.validate_config(c)
    c["watermark"]["retired_keys"] = [{"hashing_key": "99", "key_id": "11111111"}]
    with pytest.raises(ValueError, match="retired_keys"):
        cfg.validate_config(c)


def _keyed():
    """A valid config with a distinct key per model."""
    c = good()
    key, num = 100001, 0
    for name, entry in c["models"].items():
        entry["watermark"].update(hashing_key=key, key_id="{:08x}".format(num))
        key += 1
        num += 1
    c["models"]["qwen05"]["watermark"]["hashing_key"] = 12345
    c["watermark"]["hashing_key"] = 12345
    c["models"]["qwen05"]["watermark"]["key_id"] = "00000000"
    c["watermark"]["key_id"] = "00000000"
    return c


def test_fresh_config_gives_every_model_its_own_key(tmp_path):
    c = cfg.load_config(tmp_path / "wm.json", [])
    keys = [e["watermark"]["hashing_key"] for e in c["models"].values()]
    ids = [e["watermark"]["key_id"] for e in c["models"].values()]
    assert len(set(keys)) == len(keys) and len(set(ids)) == len(ids)
    assert all(k != cfg.HF_PUBLIC_KEY for k in keys)
    cfg.validate_config(c)


def test_version_2_file_keeps_its_key_as_the_default_entry(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text(json.dumps({"config_version": 2, "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
                                "watermark": {"greenlist_ratio": 0.5, "bias": 3.0,
                                              "seeding_scheme": "selfhash", "context_width": 5,
                                              "hashing_key": 424242, "key_id": "0a1b2c3d",
                                              "retired_keys": [],
                                              "ignore_repeated_ngrams": True}}), encoding="utf-8")
    notes = []
    c = cfg.load_config(path, notes)
    assert c["config_version"] == 3 and c["default_model"] == "qwen05"
    assert c["models"]["qwen05"]["watermark"]["hashing_key"] == 424242
    assert c["models"]["smol360"]["watermark"]["hashing_key"] not in (None, 424242)
    assert any("each with its own private watermark key" in n for n in notes)
    cfg.validate_config(c)


def test_unknown_model_id_becomes_a_custom_entry(tmp_path):
    path = tmp_path / "wm.json"
    path.write_text(json.dumps({"model_id": "org/custom-model",
                                "watermark": {"hashing_key": 777}}), encoding="utf-8")
    c = cfg.load_config(path, [])
    assert c["default_model"] == "custom"
    assert c["models"]["custom"]["watermark"]["hashing_key"] == 777
    assert c["model_id"] == "org/custom-model"
    cfg.validate_config(c)


def test_config_for_model_resolves_one_entry():
    c = _keyed()
    r = cfg.config_for_model(c, "smol360")
    assert r["model_id"] == "HuggingFaceTB/SmolLM2-360M-Instruct"
    assert r["watermark"]["hashing_key"] == c["models"]["smol360"]["watermark"]["hashing_key"]
    assert r["temperature"] == c["temperature"]      # shared settings stay
    with pytest.raises(ValueError, match="Unknown model"):
        cfg.config_for_model(c, "llama")


def test_two_models_may_not_share_a_key_or_an_id():
    c = _keyed()
    c["models"]["smol360"]["watermark"]["hashing_key"] = 12345
    with pytest.raises(ValueError, match="must not share"):
        cfg.validate_config(c)
    c = _keyed()
    c["models"]["smol360"]["watermark"]["key_id"] = "00000000"
    with pytest.raises(ValueError, match="already used"):
        cfg.validate_config(c)
    c = _keyed()
    c["default_model"] = "llama"
    with pytest.raises(ValueError, match="default_model"):
        cfg.validate_config(c)


def test_rotating_a_named_model_keeps_the_default_untouched(tmp_path):
    path = tmp_path / "wm.json"
    before = cfg.load_config(path)
    old, new = cfg.rotate_key(path, model="smol360")
    now = cfg.load_config(path)
    assert old == before["models"]["smol360"]["watermark"]["key_id"]
    assert new == now["models"]["smol360"]["watermark"]["key_id"] != old
    assert now["watermark"]["key_id"] == before["watermark"]["key_id"]   # default kept
    name, scored = cfg.config_for_key(now, old)
    assert name == "smol360"


def test_public_models_lists_everything_but_the_keys():
    shown = cfg.public_models(_keyed())
    assert [(m["name"], m["key_id"]) for m in shown[:2]] == [("qwen05", "00000000"),
                                                             ("qwen15", "00000001")]
    assert "hashing_key" not in json.dumps(shown)
    labels = cfg.model_label(_keyed(), "smol135")
    assert "SmolLM2 135M" in labels and "270 MB" in labels


def test_model_display_names_come_from_the_catalog():
    c = _keyed()
    assert cfg.model_display_for_id(c, "Qwen/Qwen2.5-0.5B-Instruct") == "Qwen2.5 0.5B"
    assert cfg.model_display_for_id(c, "HuggingFaceTB/SmolLM2-360M-Instruct") == "SmolLM2 360M"
    assert cfg.model_display_for_id(c, "unknown/id") == "unknown/id"
    assert cfg.model_display_for_id(c, "") == ""


def test_generated_by_text_is_plain_and_names_the_model():
    c = _keyed()
    assert cfg.generated_by_text(c, "LIKELY MARKTEXT", "Qwen/Qwen2.5-0.5B-Instruct") == \
        "Likely generated by Qwen2.5 0.5B"
    assert cfg.generated_by_text(c, "POSSIBLE WATERMARK", "x/y") == "Possibly generated by x/y"
    assert cfg.generated_by_text(c, "NOT DETECTED", "x/y") == "No AI writing found"
    assert cfg.generated_by_text(c, "INCONCLUSIVE (short text)", "") == "Too short to check"
    assert cfg.generated_by_text(c, "", "") == ""


def test_model_for_sidecar_prefers_the_name_then_the_id():
    c = _keyed()
    assert cfg.model_for_sidecar(c, {"model": "smol360"}) == "smol360"
    assert cfg.model_for_sidecar(c, {"model_id": "TinyLlama/TinyLlama-1.1B-Chat-v1.0"}) == "tinyllama"
    assert cfg.model_for_sidecar(c, {}) == "qwen05"
    assert cfg.model_for_sidecar(c, {"model": "gone", "model_id": "unknown"}) == "qwen05"
