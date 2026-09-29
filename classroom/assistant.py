"""The student's writing assistant: MarkText's own watermarked generation,
offered inside the assignment page.

Everything it drafts is watermarked, so the teacher can later tell that a
submission came from the assistant. That is the question detection
answers: "was this drafted with the assistant", not "was this AI-written".

The feature sits behind one switch, classroom.assistant_enabled in
config/watermark_config.json. To remove it:
- soft: set the switch to false. The assistant card disappears from the
  student page (tested in tests/test_app_flows.py).
- hard: delete this file and tests/test_assistant.py, the block guarded by
  `assistant.enabled(config)` in app_pages/student_assignment.py, and the
  classroom.assistant_* keys in config.py (DEFAULT_CONFIG and
  validate_config) and config/watermark_config.example.json. Keep
  "assistant" in submissions.SOURCES so old submissions still read.
  `grep -rn assistant --include=*.py` lists every site.
"""

MIN_TOKENS = 50
MAX_PROMPT = 1000
# the lengths offered: from 150, because a draft needs about 100 scored
# tokens for a verdict and some tokens are not scored (the first few, and
# repeats); a 100-token draft always came back inconclusive
LENGTHS = (150, 200, 250, 300)


def enabled(config):
    return bool(config.get("classroom", {}).get("assistant_enabled", False))


def max_tokens(config):
    return int(config.get("classroom", {}).get("assistant_max_tokens", 300))


def draft(engine, lock, prompt, max_new_tokens=None, cancel_event=None):
    """Generate a watermarked draft (always watermarked). Returns the
    engine's result dict; the length is clamped to the configured limit."""
    prompt = " ".join((prompt or "").split())
    if not prompt:
        raise ValueError("Tell the assistant what to write.")
    if len(prompt) > MAX_PROMPT:
        raise ValueError("Keep the request under {} characters.".format(MAX_PROMPT))
    limit = max_tokens(engine.config)
    length = max(MIN_TOKENS, min(int(max_new_tokens or limit), limit))
    with lock:
        return engine.generate(prompt, max_new_tokens=length, watermarked=True,
                               cancel_event=cancel_event)


def generation_record(info, prompt):
    """What a submission's sidecar keeps about a draft (never the key): how
    it was made, and the draft itself, so the teacher can see what the
    student changed."""
    return {"prompt": prompt,
            "text": info.get("text", ""),
            "seed": info.get("seed"),
            "mode": info.get("mode"),
            "model_id": info.get("model_id"),
            "max_new_tokens": info.get("max_new_tokens"),
            "new_tokens": info.get("new_tokens"),
            "device": info.get("device"),
            "key_id": (info.get("watermark") or {}).get("key_id"),
            "cancelled": bool(info.get("cancelled", False))}
