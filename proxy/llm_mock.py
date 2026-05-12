import os
import re
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from google import genai

# Load the .env file from the project root (one level up from proxy/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

# Ordered list of models to try — if one hits a rate limit, fall back to the next
FALLBACK_MODELS: List[str] = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
]

# Retry configuration
MAX_RETRIES: int = 2
BASE_RETRY_DELAY: float = 3.0  # seconds


# ---------------------------------------------------------------------------
# Local Fallback Mock Responses (no LLM needed)
# ---------------------------------------------------------------------------
# Maps URL patterns to realistic mock responses for common APIs.
# Used when Gemini is unavailable or rate-limited.

LOCAL_MOCKS: Dict[str, Dict[str, Any]] = {
    "stripe.com": {
        "object": "list",
        "url": "/v1/charges",
        "has_more": False,
        "data": [
            {
                "id": "ch_3Qx2Y2eZvKYlo2C10u2TkS5O",
                "object": "charge",
                "amount": 2999,
                "currency": "usd",
                "status": "succeeded",
                "paid": True,
                "description": "Sandbox mock charge",
                "customer": "cus_PqR5sT7uvWxYzA",
                "created": 1715500000,
                "livemode": False,
            }
        ],
    },
    "api.openai.com": {
        "id": "chatcmpl-mock-abc123",
        "object": "chat.completion",
        "created": 1715500000,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "This is a mock response from the sandbox."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
    },
    "amazonaws.com": {
        "ResponseMetadata": {
            "RequestId": "mock-req-id-12345",
            "HTTPStatusCode": 200,
            "HTTPHeaders": {},
        },
        "mock": True,
        "message": "Sandbox mock AWS response",
    },
    "graph.facebook.com": {
        "data": [],
        "paging": {"cursors": {"before": "mock_before", "after": "mock_after"}},
    },
}


def _generate_local_fallback(method: str, url: str, payload: str) -> str:
    """
    Generates a mock response locally without needing an LLM.
    Matches the URL against known API patterns, or returns a generic mock.
    """
    # Check if the URL matches any known API pattern
    for pattern, mock_data in LOCAL_MOCKS.items():
        if pattern in url:
            print(f"[MockLLM] Using local fallback for matched pattern: {pattern}")
            return json.dumps(mock_data, indent=2)

    # Generic fallback for unknown APIs
    print(f"[MockLLM] Using generic local fallback for: {url}")
    return json.dumps({
        "status": "ok",
        "message": "Sandbox mock response (Gemini unavailable)",
        "request": {"method": method, "url": url},
        "data": {
            "id": "mock-id-sandbox-001",
            "created_at": "2026-05-12T00:00:00Z",
            "mock": True,
        },
    }, indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_response(text: str) -> str:
    """Strips markdown code fences if the model wraps the JSON despite instructions."""
    result = text.strip()
    if result.startswith("```json"):
        result = result[7:]
    elif result.startswith("```"):
        result = result[3:]
    if result.endswith("```"):
        result = result[:-3]
    return result.strip()


def _extract_retry_delay(error_msg: str) -> float:
    """Extracts the retry delay suggested by the API from the error message."""
    match = re.search(r"retry in (\d+\.?\d*)", error_msg, re.IGNORECASE)
    if match:
        return min(float(match.group(1)), 10.0)  # Cap at 10s to avoid curl timeouts
    return BASE_RETRY_DELAY


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

async def generate_mock_response(method: str, url: str, payload: str) -> str:
    """
    Dynamically generates a realistic JSON response for intercepted HTTP requests.
    Tries Google Gemini first (with retry + fallback models), then falls back to
    local pattern-matched mock responses if all LLM attempts fail.
    """
    api_key = os.environ.get("GEMINI_API_KEY")

    # If no API key, skip LLM entirely and use local fallback
    if not api_key:
        print("[MockLLM] No GEMINI_API_KEY set. Using local fallback.")
        return _generate_local_fallback(method, url, payload)

    # Initialize the google-genai client
    client = genai.Client(api_key=api_key)

    prompt = (
        f"You are a universal API mock server. The client requested "
        f"{method} {url} with payload: {payload}. "
        f"Generate a highly realistic, valid JSON response that this API would naturally return. "
        f"Return ONLY the raw JSON string. Do not use markdown blocks, no formatting, no explanations."
    )

    last_error: str = ""

    # Try each model in the fallback chain
    for model_name in FALLBACK_MODELS:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                print(f"[MockLLM] Success with model={model_name} on attempt {attempt}")
                return _clean_response(response.text)

            except Exception as e:
                last_error = str(e)
                is_rate_limit = "429" in last_error or "quota" in last_error.lower()

                if is_rate_limit and attempt < MAX_RETRIES:
                    delay = _extract_retry_delay(last_error)
                    print(f"[MockLLM] Rate limited on {model_name} (attempt {attempt}). "
                          f"Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    continue
                elif is_rate_limit:
                    print(f"[MockLLM] Rate limit persists on {model_name}. "
                          f"Falling back to next model...")
                    break
                else:
                    print(f"[MockLLM] Error on {model_name}: {last_error}")
                    break

    # All LLM models exhausted — use local fallback instead of returning an error
    print("[MockLLM] All Gemini models exhausted. Falling back to local mock generator.")
    return _generate_local_fallback(method, url, payload)
