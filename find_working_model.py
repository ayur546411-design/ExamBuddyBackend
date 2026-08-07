"""
find_working_model.py — Test each available model to find one that works
"""
from google import genai
from google.genai import types
import os

with open(".env") as f:
    for line in f:
        if line.startswith("GEMINI_API_KEY="):
            api_key = line.strip().split("=", 1)[1]
            break

client = genai.Client(api_key=api_key)

# Models most likely to work for text generation (not image/audio/embedding)
CANDIDATES = [
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-pro-latest",
    "gemini-2.0-flash-001",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.0-flash",
    "gemini-3-pro-preview",
]

print("Testing models with new google.genai SDK:")
print("=" * 60)
working = []

for model_name in CANDIDATES:
    try:
        resp = client.models.generate_content(
            model=model_name,
            contents="Reply with just the word: WORKING",
            config=types.GenerateContentConfig(max_output_tokens=10, temperature=0)
        )
        text = resp.text.strip()
        print(f"  OK    {model_name:40s} -> '{text}'")
        working.append(model_name)
    except Exception as e:
        err = str(e)[:120]
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            print(f"  QUOTA {model_name:40s} -> QUOTA EXCEEDED")
            working.append(f"QUOTA:{model_name}")  # Add as quota-limited (will work later)
        elif "404" in err:
            print(f"  404   {model_name:40s} -> NOT FOUND/UNAVAILABLE")
        else:
            print(f"  FAIL  {model_name:40s} -> {err[:80]}")

print("\n" + "=" * 60)
print("WORKING or QUOTA models (will work when quota resets):")
for m in working:
    print(f"  {m}")
