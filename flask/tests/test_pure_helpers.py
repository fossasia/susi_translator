from __future__ import annotations


def test_merge_returns_dict_shape_not_strings(ts):
    """merging returns structured dictionaries rather than raw strings"""
    inp = {"100": {"transcript": "Hello world."}}
    out = ts.merge_and_split_transcripts(inp)
    assert isinstance(out["100"], dict)
    assert "transcript" in out["100"]


def test_merge_handles_dict_values_without_attributeerror(ts):
    """verifies sequential chunks are combined into sentence fragments smoothly"""
    inp = {
        "100": {"transcript": "Hello world this is"},
        "200": {"transcript": "a test. And more."},
    }
    out = ts.merge_and_split_transcripts(inp)
    joined = " ".join(v["transcript"] for v in out.values())
    assert "Hello world this is a test." in joined
    assert "And more." in joined


def test_merge_empty_input_returns_empty(ts):
    """ensures empty payloads return an empty dictionary gracefully"""
    assert ts.merge_and_split_transcripts({}) == {}


def test_merge_tail_attaches_to_last_key_when_no_terminator(ts):
    """ensures unterminated text fragments hang onto the trailing timestamp block"""
    inp = {"5": {"transcript": "no terminator here"}}
    out = ts.merge_and_split_transcripts(inp)
    assert "5" in out
    assert out["5"]["transcript"].lower().strip().rstrip(".") == "no terminator here"


def test_merge_tolerates_empty_transcript_values(ts):
    """validates that empty string slots inside incoming chunks are handled safely"""
    inp = {
        "1": {"transcript": ""},
        "2": {"transcript": "Done."},
    }
    out = ts.merge_and_split_transcripts(inp)
    assert "Done." in out["2"]["transcript"]


def test_merge_capitalises_sentence_starts(ts):
    """verifies sentence boundaries automatically clean up casing rules"""
    inp = {"1": {"transcript": "first sentence. second sentence."}}
    out = ts.merge_and_split_transcripts(inp)
    text = out["1"]["transcript"]
    assert text.startswith("First sentence.")
    assert "Second sentence." in text