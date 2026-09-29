import copy
import json

import pytest

import config as cfg


def good():
    c = copy.deepcopy(cfg.DEFAULT_CONFIG)
    c["watermark"]["hashing_key"] = 12345
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
    assert any("public default" in n for n in notes)


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
    assert c["classroom"] == {"assistant_enabled": True, "assistant_max_tokens": 300}


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
    assert any("key id" in n for n in notes)
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
