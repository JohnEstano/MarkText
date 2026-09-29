"""Pure helpers in ui/common.py (no page is run)."""

from ui import common


def test_unique_labels_keep_the_first_and_number_the_rest():
    labels = common.unique_labels(["a", "b", "c", "d"],
                                  {"a": "Essay", "b": "Essay", "c": "Essay (2)", "d": "Other"}.get)
    assert labels == {"a": "Essay", "b": "Essay (3)", "c": "Essay (2)", "d": "Other"}
    assert len(set(labels.values())) == 4


def test_unique_labels_use_the_detail_first():
    labels = common.unique_labels(["u1", "u2", "u3"], {"u1": "Alice", "u2": "Alice", "u3": "Ben"}.get,
                                  detail=str)
    assert labels == {"u1": "Alice · u1", "u2": "Alice · u2", "u3": "Ben"}


def test_highlight_marks_each_line_of_the_passage_and_escapes_the_rest():
    text = "Intro *not bold*.\nThe drafted part\ngoes on here.\nThe end."
    start = text.index("The drafted")
    end = text.index("here.") + len("here.")
    shown = common.highlighted(text, start, end)
    assert ":orange-background[The drafted part]" in shown
    assert ":orange-background[goes on here\\.]" in shown
    assert "\\*not bold\\*" in shown and shown.count("  \n") == 3


def test_scoring_notes():
    assert common.scoring_notes("0", "", "", False) == []
    notes = common.scoring_notes("3", "5.2", "1.0e-06", True)
    assert notes[0].startswith("3 repeated phrases counted once")
    assert "z = 5.20" in notes[1] and notes[1].endswith("The verdict comes from this passage.")


def test_a_passage_decides_only_when_the_whole_text_is_under_the_threshold():
    config = {"detection_threshold": 4.0}
    base = {"label": "LIKELY MARKTEXT", "passage_z": "5.4", "passage_start": "10", "passage_end": "900"}
    assert common.passage_decided(dict(base, z_score="3.1"), config)
    assert not common.passage_decided(dict(base, z_score="4.2"), config)          # the whole text decided
    assert not common.passage_decided(dict(base, z_score="3.1", label="POSSIBLE WATERMARK"), config)
    assert not common.passage_decided(dict(base, z_score="3.1", passage_z=""), config)
    assert not common.passage_decided(None, config)
