# flask/test_fix.py — paste your fixed function here directly, no model loading needed

def merge_and_split_transcripts(transcripts):
    sec = ".!?"
    merged_transcripts = ""
    result = {}
    for key in transcripts.keys():
        if not merged_transcripts:
            merged_transcripts += transcripts[key]['transcript'].strip()
        else:
            t = transcripts[key]['transcript'].strip()
            if len(t) > 1:
                merged_transcripts += " " + t[0].lower() + t[1:]
            else:
                merged_transcripts += " " + t

        while any(char in sec for char in merged_transcripts):
            index = next(i for i, char in enumerate(merged_transcripts) if char in sec)
            head = merged_transcripts[:index + 1].strip()
            head = head[0].capitalize() + head[1:] if len(head) > 1 else head
            p = result.get(key)
            if p:
                result[key] = {'transcript': p['transcript'] + " " + head}
            else:
                result[key] = {'transcript': head}
            merged_transcripts = merged_transcripts[index + 1:].strip()

    if merged_transcripts:
        last_key = list(transcripts.keys())[-1]
        p = result.get(last_key)
        if p:
            result[last_key] = {'transcript': p['transcript'] + " " + merged_transcripts}
        else:
            result[last_key] = {'transcript': merged_transcripts}

    return result


# --- Test 1: Normal sentences with punctuation ---
transcripts = {
    "1700000000000": {"transcript": "Hello everyone."},
    "1700000001000": {"transcript": "Welcome to the event."},
    "1700000002000": {"transcript": "Let's get started."},
}
result = merge_and_split_transcripts(transcripts)
print("Test 1 result:", result)
for k, v in result.items():
    assert isinstance(v, dict), f"Expected dict at key {k}, got {type(v)}"
    assert 'transcript' in v
print(" Test 1 passed\n")

# --- Test 2: No punctuation (the original crash case) ---
transcripts2 = {
    "1700000000000": {"transcript": "Hello everyone"},
    "1700000001000": {"transcript": "welcome to the event"},
}
result2 = merge_and_split_transcripts(transcripts2)
print("Test 2 result:", result2)
last_key = list(result2.keys())[-1]
assert isinstance(result2[last_key], dict), "Last entry should be a dict"
print(" Test 2 passed\n")

# --- Test 3: Single entry ---
transcripts3 = {
    "1700000000000": {"transcript": "Just one sentence here."},
}
result3 = merge_and_split_transcripts(transcripts3)
print("Test 3 result:", result3)
assert isinstance(result3["1700000000000"], dict)
print(" Test 3 passed\n")

# --- Test 4: Empty ---
result4 = merge_and_split_transcripts({})
assert result4 == {}
print(" Test 4 passed\n")

print("🎉 All tests passed!")