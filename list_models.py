"""
list_models.py — Find valid model names for this API key using new google.genai SDK
"""
from google import genai
from google.genai import types
import os
import sys

# Load API key from .env
from dotenv import load_dotenv
load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY", "")
if not api_key:
    # Try reading directly
    with open(".env") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.strip().split("=", 1)[1]
                break

print(f"Using API key: {api_key[:15]}...")

client = genai.Client(api_key=api_key)

print("\nListing all available models that support generateContent:")
print("=" * 65)
count = 0
for model in client.models.list():
    if hasattr(model, 'supported_actions'):
        actions = model.supported_actions or []
    else:
        actions = []
    
    # Only show generative models
    name = getattr(model, 'name', '')
    display_name = getattr(model, 'display_name', '')
    
    print(f"  {name:45s} | {display_name}")
    count += 1

print(f"\nTotal models: {count}")

# Quick test with gemini-2.0-flash
print("\nTesting gemini-2.0-flash...")
try:
    resp = client.models.generate_content(
        model="gemini-2.0-flash",
        contents="Say OK",
        config=types.GenerateContentConfig(max_output_tokens=5)
    )
    print(f"  gemini-2.0-flash: OK -> '{resp.text.strip()}'")
except Exception as e:
    print(f"  gemini-2.0-flash: FAIL -> {e}")

print("\nTesting gemini-2.5-flash...")
try:
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Say OK",
        config=types.GenerateContentConfig(max_output_tokens=5)
    )
    print(f"  gemini-2.5-flash: OK -> '{resp.text.strip()}'")
except Exception as e:
    print(f"  gemini-2.5-flash: FAIL -> {e}")
