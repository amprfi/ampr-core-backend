"""
Diagnostics endpoints for testing external service latency.
"""

import os
import time
import logging
import httpx

from fastapi import APIRouter, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")

MODELS = [
    "mistral-small-latest",
    "mistral-large-latest",
]

TEST_PROMPT = "Reply with exactly one word: hello."

DUMMY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_price",
            "description": "Get stock price by ticker symbol.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
]


@router.get("/mistral-latency", status_code=status.HTTP_200_OK)
async def test_mistral_latency():
    """
    Test Mistral API response latency across models.
    Sends a minimal prompt with and without tools, and reports the
    resolved model version.
    """
    results = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for model in MODELS:
            headers = {
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json",
            }

            for mode, tools in [("no_tools", None), ("with_tools", DUMMY_TOOLS)]:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": TEST_PROMPT}],
                    "max_tokens": 10,
                }
                if tools:
                    payload["tools"] = tools

                start = time.monotonic()
                try:
                    resp = await client.post(MISTRAL_API_URL, json=payload, headers=headers)
                    elapsed = round(time.monotonic() - start, 3)
                    resp_data = resp.json()

                    reply = ""
                    resolved_model = resp_data.get("model", "unknown")
                    if resp.status_code == 200:
                        choices = resp_data.get("choices", [])
                        if choices:
                            reply = choices[0].get("message", {}).get("content", "")

                    results.append({
                        "model_requested": model,
                        "model_resolved": resolved_model,
                        "mode": mode,
                        "status": resp.status_code,
                        "latency_seconds": elapsed,
                        "reply": reply,
                    })
                except Exception as e:
                    elapsed = round(time.monotonic() - start, 3)
                    results.append({
                        "model_requested": model,
                        "mode": mode,
                        "status": "error",
                        "latency_seconds": elapsed,
                        "error": str(e),
                    })

    return {"results": results}
