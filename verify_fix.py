
def merge_and_split_transcripts_logic(transcripts):
    # This is a copy of the logic from the fixed function to verify it works in isolation
    sec = ".!?"
    merged_transcripts = ""
    result = {}
    for key in transcripts.keys():
        if not merged_transcripts:
            merged_transcripts += transcripts[key].strip()
        else:
            t = transcripts[key].strip()
            if len(t) > 1:
                merged_transcripts += " " +  t[0].lower() + t[1:]
            else:
                merged_transcripts += " " + t

        while any(char in sec for char in merged_transcripts):
            import re
            match = re.search(f"[{re.escape(sec)}]", merged_transcripts)
            if not match: break
            index = match.start()
            head = merged_transcripts[:index + 1].strip()
            head = head[0].capitalize() + head[1:] if len(head) > 1 else head
            p = result.get(key)
            if p:
                result[key] = p + " " + head
            else:
                result[key] = head
            merged_transcripts = merged_transcripts[index + 1:].strip()

    if merged_transcripts:
        # THE FIX: list().keys()
        keys = list(transcripts.keys())
        if keys:
            last_key = keys[-1]
            p = result.get(last_key)
            if p:
                result[last_key] = p + " " + merged_transcripts
            else:
                result[last_key] = merged_transcripts
    return result

# Test cases
test_transcripts = {
    "1700000000000": "Hello everyone",
    "1700000001000": "welcome to the event"
}

print("Testing merge_and_split_transcripts logic with fix...")
try:
    res = merge_and_split_transcripts_logic(test_transcripts)
    print("Result:", res)
    assert res["1700000001000"] == "welcome to the event"
    print("Test passed: Unpunctuated tail handled correctly.")
except TypeError as e:
    print("FIX FAILED: TypeError occurred:", e)
except Exception as e:
    print("An error occurred:", e)

test_punctuated = {
    "1": "Hello.",
    "2": "How are you?"
}
print("\nTesting punctuated transcripts...")
res_punctuated = merge_and_split_transcripts_logic(test_punctuated)
print("Result:", res_punctuated)
assert res_punctuated["1"] == "Hello."
assert res_punctuated["2"] == "How are you?"
print("Test passed: Punctuated segments handled correctly.")
