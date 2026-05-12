"""Quick diagnostic script to test Gemini API key and list available models."""
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai

# Load key from .env
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
api_key = os.environ.get("GEMINI_API_KEY")

print(f"API Key loaded: {'YES' if api_key else 'NO'}")
print(f"Key prefix: {api_key[:12]}..." if api_key else "N/A")
print("-" * 50)

client = genai.Client(api_key=api_key)

# 1. List available models
print("\n=== Available Models ===")
try:
    for model in client.models.list():
        if "flash" in model.name.lower() or "gemini" in model.name.lower():
            print(f"  {model.name}")
except Exception as e:
    print(f"  ERROR listing models: {e}")

# 2. Try a simple generation with each model
test_models = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]
print("\n=== Testing Generation ===")
for model_name in test_models:
    try:
        response = client.models.generate_content(
            model=model_name,
            contents="Say hello in JSON format. Return only: {\"message\": \"hello\"}"
        )
        print(f"  {model_name}: OK -> {response.text[:80]}")
    except Exception as e:
        error_str = str(e)
        if "429" in error_str:
            print(f"  {model_name}: RATE LIMITED (429)")
        elif "404" in error_str:
            print(f"  {model_name}: NOT FOUND (404)")
        else:
            print(f"  {model_name}: ERROR -> {error_str[:100]}")

print("\nDone.")
