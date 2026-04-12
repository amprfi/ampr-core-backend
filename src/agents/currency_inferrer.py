from pathlib import Path
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Union
from convex import ConvexClient
import logging

from ..clients.async_convex_client import AsyncConvexClient

logger = logging.getLogger(__name__)

class CurrencyInferrerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: Union[ConvexClient, AsyncConvexClient]
    user_id: str

class CurrencyInference(BaseModel):
    """Structured output from the currency inferrer."""
    asset_currencies: Optional[List[str]] = Field(
        None,
        description="List of 'ASSET in CURRENCY_CODE' mappings when user requests specific assets in specific currencies, e.g., ['BTC in USD', 'ETH in EUR']. If multiple assets should all be in the same currency, list each one separately."
    )

PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/currency_inferrer.md").read_text()

_agent = Agent(
    "mistral:mistral-small-latest",
    deps_type=CurrencyInferrerContext,
    output_type=CurrencyInference,
    system_prompt=PROMPT_TEMPLATE,
)


async def infer_display_currency(
    message: str,
    user_id: str,
    convex_client: Union[ConvexClient, AsyncConvexClient],
) -> str:
    """
    Determine the display currency for a user message.
    
    1. Run the LLM agent to detect currency intent in the message
    2. If specific asset-currency pairs found, return them as a formatted list
    3. If a general currency requested, return "display_currency: CODE"
    4. If no currency intent detected, query the user's stored preference from DB
    5. Return "display_currency: CODE" with the stored default (or USD if none set)
    """
    try:
        ctx = CurrencyInferrerContext(convex_client=convex_client, user_id=user_id)
        result = await _agent.run(message, deps=ctx)
        inference = result.output

        # Asset-currency pairs detected
        if inference.asset_currencies:
            currency_context = "\n".join(inference.asset_currencies)
            logger.info(f"Currency inferrer detected asset-specific currencies for user {user_id}: {inference.asset_currencies}")
            return currency_context

    except Exception as e:
        logger.warning(f"Currency inferrer LLM failed for user {user_id}, falling back to stored preference: {e}")

    # Case 3: No currency intent — fall back to stored preference
    try:
        if isinstance(convex_client, AsyncConvexClient):
            currency_data = await convex_client.query("profiles:getUserCurrency", {"userId": user_id})
        else:
            currency_data = convex_client.query("profiles:getUserCurrency", {"userId": user_id})

        stored_currency = currency_data.get("preferred_currency") if currency_data else None
        default = stored_currency.upper() if stored_currency else "USD"
    except Exception as e:
        logger.warning(f"Failed to fetch stored currency for user {user_id}, defaulting to USD: {e}")
        default = "USD"

    logger.info(f"Currency inferrer using stored preference for user {user_id}: {default}")
    return f"display_currency: {default}"
