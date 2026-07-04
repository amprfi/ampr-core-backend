from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
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

HORIZON_MAP = {
    "E_1_5": "1-5",
    "E_6_10": "6-10",
    "E_10_20": "10-20",
    "E_20PLUS": "20 plus",
    # Pass through if already correct
    "1-5": "1-5",
    "6-10": "6-10",
    "10-20": "10-20",
    "20 plus": "20 plus",
}

KNOWLEDGE_MAP = {
    "NOVICE": "novice",
    "INTERMEDIATE": "intermediate",
    "ADVANCED": "advanced",
    "novice": "novice",
    "intermediate": "intermediate",
    "advanced": "advanced",
}


class ExtractedProfile(BaseModel):
    inferred_investment_horizon: Optional[str] = Field(
        None,
        description="Investment timeframe: 1-5 (short-term), 6-10 (medium-term), 10-20 (long-term), or 20 plus (very long-term)"
    )
    inferred_risk_appetite: Optional[int] = Field(
        None,
        ge=1,
        le=5,
        description="Risk tolerance from 1 (very conservative) to 5 (very aggressive)"
    )
    inferred_investment_knowledge: Optional[str] = Field(
        None,
        description="Investment expertise: novice, intermediate, or advanced"
    )
    inferred_financial_goals: Optional[List[str]] = Field(
        None,
        description="List of financial goals mentioned (e.g., 'retirement', 'home purchase', 'wealth building')"
    )
    inferred_investment_thesis: Optional[str] = Field(
        None,
        description="User's overall investment philosophy or thesis synthesized from conversations"
    )
    country_name: Optional[str] = Field(
        None,
        description="Country name or ISO 3166-1 alpha-3 code mentioned as user's residence (e.g., 'Canada', 'CAN')"
    )
    preferred_currency: Optional[str] = Field(
        None,
        description="ISO 4217 currency code mentioned as user's preferred currency (e.g., 'USD', 'CAD', 'EUR')"
    )
    email: Optional[str] = Field(
        None,
        description="Email address mentioned by the user"
    )
    phone: Optional[str] = Field(
        None,
        description="Phone number mentioned by the user"
    )


PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/extractor.md").read_text()


async def _get_current_profile_context(
    convex_client: Union[ConvexClient, AsyncConvexClient],
    user_id: str
) -> str:
    """
    Get the current inferred profile data for this user as context string.

    This replaces the pydantic-ai tool with a direct DB fetch, injected into the prompt.
    """
    logger.info(f"Fetching current profile context for user_id={user_id}")
    try:
        client = convex_client
        profile_summary = []

        # Fetch investment preferences
        if isinstance(client, AsyncConvexClient):
            result = await client.query("profiles:getInvestmentPreferences", {
                "userId": user_id
            })
        else:
            result = client.query("profiles:getInvestmentPreferences", {
                "userId": user_id
            })

        if result:
            if result.get("inferred_investment_horizon"):
                profile_summary.append(f"Investment horizon: {result['inferred_investment_horizon']}")
            if result.get("inferred_risk_appetite"):
                profile_summary.append(f"Risk appetite: {result['inferred_risk_appetite']}")
            if result.get("inferred_investment_knowledge"):
                profile_summary.append(f"Investment knowledge: {result['inferred_investment_knowledge']}")
            if result.get("inferred_financial_goals"):
                profile_summary.append(f"Financial goals: {', '.join(result['inferred_financial_goals'])}")
            if result.get("inferred_investment_thesis"):
                profile_summary.append(f"Investment thesis: {result['inferred_investment_thesis']}")

        # Fetch watchable profile fields (currency, country, email, phone)
        if isinstance(client, AsyncConvexClient):
            currency_data = await client.query("profiles:getUserCurrency", {"userId": user_id})
            country_data = await client.query("profiles:getUserCountry", {"userId": user_id})
            user_data = await client.query("users:getUser", {"userId": user_id})
        else:
            currency_data = client.query("profiles:getUserCurrency", {"userId": user_id})
            country_data = client.query("profiles:getUserCountry", {"userId": user_id})
            user_data = client.query("users:getUser", {"userId": user_id})

        if currency_data and currency_data.get("preferred_currency"):
            profile_summary.append(f"Preferred currency: {currency_data['preferred_currency']}")
        country = country_data.get("country") if country_data else None
        if country and country.get("country_name"):
            profile_summary.append(f"Country: {country['country_name']}")
        if user_data:
            if user_data.get("email"):
                profile_summary.append(f"Email: {user_data['email']}")
            if user_data.get("phone"):
                profile_summary.append(f"Phone: {user_data['phone']}")

        if not profile_summary:
            return "No existing profile data found. All fields are empty."

        logger.info(f"Profile context: {len(profile_summary)} fields")
        return "\n".join(profile_summary)
    except Exception as e:
        error_msg = f"Error retrieving current profile: {str(e)}"
        logger.error(f"Profile context fetch error: {error_msg}")
        return error_msg


class ExtractorAgent:
    """
    Extractor agent using Mistral SDK with structured JSON output.

    Extracts user profile information from messages. Prefetches current profile
    context and injects it into the prompt instead of using a tool loop.
    """

    def __init__(self):
        self.client = get_shared_client()
        self.system_prompt = PROMPT_TEMPLATE
        self.schema = ExtractedProfile.model_json_schema()

    async def run(
        self,
        message: str,
        convex_client: Union[ConvexClient, AsyncConvexClient],
        user_id: str,
    ) -> ExtractedProfile:
        """
        Run the extractor on the given message with profile context.

        Args:
            message: The message to extract profile info from
            convex_client: Convex client for fetching profile data
            user_id: The user ID for fetching profile data

        Returns:
            ExtractedProfile with extracted fields
        """
        # Prefetch current profile context
        profile_context = await _get_current_profile_context(convex_client, user_id)

        # Inject profile context into the user message
        user_content = f"Current profile:\n{profile_context}\n\nMessage to analyze:\n{message}"

        messages = build_messages(self.system_prompt, user_content)

        try:
            result_dict = await complete_json_schema(
                client=self.client,
                model=MODEL_SMALL,
                messages=messages,
                schema=self.schema,
                temperature=0.1,
                reasoning_effort="none",
            )

            extracted = ExtractedProfile(**result_dict)
            logger.info(f"Extractor parsed result with {len(result_dict)} fields")
            return extracted

        except Exception as e:
            logger.error(f"Extractor failed: {e}", exc_info=True)
            # Graceful fallback: return empty profile
            return ExtractedProfile()


# Singleton instance
_agent_instance: ExtractorAgent | None = None


def get_extractor_agent() -> ExtractorAgent:
    """
    Get an extractor agent instance.

    Returns:
        Singleton ExtractorAgent instance
    """
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ExtractorAgent()
    return _agent_instance
