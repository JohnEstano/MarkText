import json
import threading

import pytest
from fakes import FakeEngine, fake_config

from classroom import assistant


def test_the_switch():
    assert assistant.enabled(fake_config())
    assert not assistant.enabled(fake_config(assistant_enabled=False))
    assert not assistant.enabled({})                     # no classroom block: off


def test_drafts_are_always_watermarked_and_clamped():
    eng = FakeEngine(fake_config(assistant_max_tokens=200))
    info = assistant.draft(eng, threading.Lock(), "  Write   about diaries ", 5000)
    assert info["mode"] == "watermarked" and info["new_tokens"] == 200
    assert eng.generated == [("Write about diaries", 200, True)]
    assistant.draft(eng, threading.Lock(), "Short one", 10)
    assert eng.generated[-1][1] == assistant.MIN_TOKENS
    with pytest.raises(ValueError, match="what to write"):
        assistant.draft(eng, threading.Lock(), "   ")


def test_generation_record_has_no_key():
    eng = FakeEngine()
    info = assistant.draft(eng, threading.Lock(), "Write about diaries", 100)
    record = assistant.generation_record(info, "Write about diaries")
    assert record["key_id"] == "0a1b2c3d" and record["seed"] == 42 and record["mode"] == "watermarked"
    assert "424242" not in json.dumps(record)
