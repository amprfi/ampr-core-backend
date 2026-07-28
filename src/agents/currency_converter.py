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

from .mistral_helpers import (
    get_shared_client,
    build_messages,
    complete_text,
    MODEL_SMALL,
)

logger = logging.getLogger(__name__)

TIINGO_BASE_URL = "https://api.tiingo.com/tiingo/fx"
TIINGO_API_KEY = os.environ.get("TIINGO_API_KEY", "")

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

    messages = build_messages(PROMPT_TEMPLATE, user_content)

    try:
        client = get_shared_client()
        converted = await complete_text(
            client=client,
            model=MODEL_SMALL,
            messages=messages,
            temperature=0.7,
            reasoning_effort="high",
        )

        logger.info(f"Successfully converted response to {target_currency}")
        return converted

    except Exception as e:
        logger.error(f"Currency conversion agent failed: {e}")
        return module_response
