from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, List, Union
from convex import ConvexClient
import logging

from ..clients.async_convex_client import AsyncConvexClient
from .mistral_helpers import (
    get_shared_client,
    build_messages,
    complete_json_schema,
    MODEL_SMALL,
)

logger = logging.getLogger(__name__)


class CurrencyInference(BaseModel):
    """Structured output from the currency inferrer."""
    asset_currencies: Optional[List[str]] = Field(
        None,
        description="List of 'ASSET in CURRENCY_CODE' mappings when user requests specific assets in specific currencies, e.g., ['BTC in USD', 'ETH in EUR']. If multiple assets should all be in the same currency, list each one separately."
    )


PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/currency_inferrer.md").read_text()


class CurrencyInferrerAgent:
    """
    Currency inferrer agent using Mistral SDK with structured JSON output.

    Uses response_format: json_schema with strict: true for guaranteed
    structured output validation.
    """

    def __init__(self):
        self.client = get_shared_client()
        self.system_prompt = PROMPT_TEMPLATE
        self.schema = CurrencyInference.model_json_schema()

    async def run(self, message: str) -> CurrencyInference:
        """
        Run the currency inferrer on the given message.

        Args:
            message: The user message to analyze for currency intent

        Returns:
            CurrencyInference with parsed structured output
        """
        messages = build_messages(self.system_prompt, message)

        try:
            # Use structured output with json_schema strict mode
            result_dict = await complete_json_schema(
                client=self.client,
                model=MODEL_SMALL,
                messages=messages,
                schema=self.schema,
                temperature=0.0,
                reasoning_effort="none",
            )

            inference = CurrencyInference(**result_dict)
            logger.info(f"Currency inferrer parsed result: {inference}")
            return inference

        except Exception as e:
            logger.error(f"Currency inferrer failed: {e}", exc_info=True)
            # Graceful fallback: return empty inference
            return CurrencyInference()


# Singleton instance
_agent_instance: CurrencyInferrerAgent | None = None


def get_currency_inferrer_agent() -> CurrencyInferrerAgent:
    """
    Get a currency inferrer agent instance.

    Returns:
        Singleton CurrencyInferrerAgent instance
    """
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CurrencyInferrerAgent()
    return _agent_instance


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
        agent = get_currency_inferrer_agent()
        inference = await agent.run(message)

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
