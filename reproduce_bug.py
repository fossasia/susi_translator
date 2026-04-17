
transcripts = {
    "1700000000000": {"transcript": "Hello everyone"},
    "1700000001000": {"transcript": "welcome to the event"}
}

print("Testing dict.keys() indexing in Python 3...")
try:
    last_key = transcripts.keys()[-1]
    print(f"Last key: {last_key}")
except TypeError as e:
    print(f"Caught expected error: {e}")

# Fix check
print("\nTesting with list(dict.keys()) indexing...")
try:
    last_key = list(transcripts.keys())[-1]
    print(f"Last key (fixed): {last_key}")
except Exception as e:
    print(f"Unexpected error with fix: {e}")
