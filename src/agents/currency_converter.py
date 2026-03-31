"""
Currency conversion subagent.

Fetches the USD -> target exchange rate from Tiingo and uses a small
Mistral model (with reasoning) to rewrite a financial response with converted
monetary values.
"""

from pathlib import Path
import httpx
import os
import logging

logger = logging.getLogger(__name__)

TIINGO_BASE_URL = "https://api.tiingo.com/tiingo/fx"
TIINGO_API_KEY = os.environ.get("TIINGO_API_KEY", "")

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MODEL = "mistral-small-latest"

PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/currency_converter.md").read_text()


async def fetch_exchange_rate(target_currency: str) -> float | None:
    """
    Fetch the USD -> target_currency exchange rate from Tiingo.

    Tiingo forex tickers are formatted as "<target>usd" (lowercase). The
    top-of-book midPrice represents how many USD one unit of the target
    currency is worth, so the USD -> target rate is 1 / midPrice.

    Returns the exchange rate as a float, or None if the request fails
    or the currency is not supported.
    """
    ticker = f"{target_currency.lower()}usd"
    url = f"{TIINGO_BASE_URL}/{ticker}/top"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Token {TIINGO_API_KEY}"},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data or not isinstance(data, list) or len(data) == 0:
            logger.warning(f"Tiingo returned no data for ticker {ticker}: {data}")
            return None

        mid_price = data[0].get("midPrice")
        if not mid_price:
            logger.warning(f"Tiingo missing midPrice for ticker {ticker}: {data[0]}")
            return None

        # midPrice = USD per 1 target unit, so invert for USD -> target rate
        rate = 1.0 / float(mid_price)
        logger.info(f"Fetched exchange rate USD -> {target_currency.upper()}: {rate}")
        return rate

    except Exception as e:
        logger.error(f"Failed to fetch exchange rate USD -> {target_currency}: {e}")
        return None


async def convert_currency(module_response: str, target_currency: str) -> str:
    """
    Convert USD values in a module response to the target currency.

    Fetches the exchange rate from Tiingo, then uses Mistral (with
    reasoning) to rewrite the response with converted values.

    Returns the original response unchanged if:
    - The exchange rate cannot be fetched
    - The LLM conversion fails
    """
    rate = await fetch_exchange_rate(target_currency)
    if rate is None:
        logger.warning(f"Could not fetch rate for {target_currency}, returning original USD response")
        return module_response

    user_content = (
        f"Exchange rate: 1 USD = {rate} {target_currency.upper()}\n"
        f"Target currency: {target_currency.upper()}\n\n"
        f"Text to convert:\n{module_response}"
    )

    messages = [
        {"role": "system", "content": PROMPT_TEMPLATE},
        {"role": "user", "content": user_content},
    ]

    body = {
        "model": MODEL,
        "messages": messages,
        "reasoning_effort": "high",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                MISTRAL_API_URL,
                headers={
                    "Authorization": f"Bearer {MISTRAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]

        # With reasoning enabled, Mistral returns content as a list of blocks
        # (thinking + text) rather than a plain string. Extract just the text.
        if isinstance(content, list):
            text_parts = [
                block["text"] for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            converted = "\n".join(text_parts)
        else:
            converted = content

        logger.info(f"Successfully converted response to {target_currency}")
        return converted

    except Exception as e:
        logger.error(f"Currency conversion agent failed: {e}")
        return module_response
