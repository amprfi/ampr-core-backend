import logging
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent, RunContext

from convex import ConvexClient

logger = logging.getLogger(__name__)


class OnboardingContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str
    telegram_id: Optional[str] = None


agent = Agent(
    "mistral:mistral-medium-latest", deps_type=OnboardingContext, output_type=str
)


@agent.tool
async def get_user_info(ctx: RunContext[OnboardingContext]) -> dict:
    """
    Get the current user's information from the database to see what's already filled in.
    Returns user fields like first_name, last_name, email, phone, telegram_id.
    """
    logger.info(f"Tool called: get_user_info for user_id={ctx.deps.user_id}")
    user = ctx.deps.convex_client.query("users:getUser", {"userId": ctx.deps.user_id})
    if not user:
        raise ValueError(f"User {ctx.deps.user_id} not found")

    return {
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "email": user.get("email"),
        "phone": user.get("phone"),
        "telegram_id": user.get("telegram_id"),
    }


@agent.tool
async def update_user_info(
    ctx: RunContext[OnboardingContext],
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    telegram_id: Optional[str] = None,
) -> str:
    """
    Update the user's information in the database.
    Only provide the fields you want to update.
    Returns success message or error.
    """
    logger.info(f"Tool called: update_user_info for user_id={ctx.deps.user_id}")
    update_data = {}
    if first_name is not None:
        update_data["first_name"] = first_name
    if last_name is not None:
        update_data["last_name"] = last_name
    if email is not None:
        update_data["email"] = email
    if phone is not None:
        update_data["phone"] = phone
    if telegram_id is not None:
        update_data["telegram_id"] = telegram_id

    if not update_data:
        return "No fields to update"

    ctx.deps.convex_client.mutation(
        "users:updateUser", {"id": ctx.deps.user_id, **update_data}
    )

    return f"Successfully updated: {', '.join(update_data.keys())}"


@agent.tool
async def set_user_country(
    ctx: RunContext[OnboardingContext], country_name: str
) -> str:
    """
    Set the user's country on their profile.
    Accepts a country name (e.g., "United States", "Germany") or ISO 3166-1 alpha-3 code (e.g., "USA", "DEU").
    Looks up the country in the database and updates the user's profile.
    """
    logger.info(
        f"Tool called: set_user_country for user_id={ctx.deps.user_id}, country_name={country_name}"
    )
    # Try looking up by code first (uppercase)
    country = ctx.deps.convex_client.query(
        "countries:getCountryByCode", {"country_code": country_name.upper()}
    )

    if not country:
        # Search all countries by name (case-insensitive partial match)
        all_countries = ctx.deps.convex_client.query("countries:getCountries", {})
        for c in all_countries:
            if country_name.lower() in c["country_name"].lower():
                country = c
                break

    if not country:
        return f"Could not find country '{country_name}'. Please try again with the full country name or 3-letter code."

    logger.info(
        f"Resolved country: id={country['_id']}, code={country['country_code']}, name={country['country_name']}"
    )

    # Upsert the profile with the country
    ctx.deps.convex_client.mutation(
        "profiles:updateProfile", {"user": ctx.deps.user_id, "country": country["_id"]}
    )

    currency = country.get("currency")
    if currency:
        return f"Country set to {country['country_name']}. The local currency is {currency}."
    return f"Country set to {country['country_name']}"


@agent.tool
async def set_user_currency(
    ctx: RunContext[OnboardingContext], currency_code: str
) -> str:
    """
    Set the user's preferred currency on their profile.
    Accepts an ISO 4217 currency code (e.g., "USD", "CAD", "EUR", "GBP").
    """
    logger.info(
        f"Tool called: set_user_currency for user_id={ctx.deps.user_id}, currency_code={currency_code}"
    )
    code = currency_code.upper().strip()

    ctx.deps.convex_client.mutation(
        "profiles:updateProfile", {"user": ctx.deps.user_id, "preferred_currency": code}
    )

    return f"Preferred currency set to {code}"


@agent.tool
async def complete_onboarding(ctx: RunContext[OnboardingContext]) -> str:
    """
    Mark the user's onboarding as complete.
    Call this when the user has provided their name OR declined to provide additional info.
    """
    logger.info(f"Tool called: complete_onboarding for user_id={ctx.deps.user_id}")
    ctx.deps.convex_client.mutation(
        "users:updateUser", {"id": ctx.deps.user_id, "onboarding_complete": True}
    )
    return "Onboarding marked as complete"


ONBOARDING_PROMPT = (Path(__file__).parent / "prompts/onboarding.md").read_text()


@agent.tool
async def validate_referral_code(
    ctx: RunContext[OnboardingContext], referral_code: str
) -> Dict[str, str]:
    """
    Validate a referral code and increment the referring user's count if valid.

    Args:
        referral_code: The referral code to validate

    Returns:
        A dictionary with:
        - success: boolean indicating if the code was valid
        - message: status message
    """
    logger.info(
        f"Tool called: validate_referral_code for user_id={ctx.deps.user_id}, referral_code={referral_code}"
    )

    # Look up the profile with this referral code
    referring_profile = ctx.deps.convex_client.query(
        "referralCodes:lookupByReferralCode", {"referralCode": referral_code}
    )

    if not referring_profile:
        return {
            "success": False,
            "message": f"Referral code {referral_code} is not valid.",
        }

    # Increment the referring user's referral count
    ctx.deps.convex_client.mutation(
        "referralCodes:incrementReferrals", {"userId": referring_profile["user"]}
    )

    return {
        "success": True,
        "message": f"Referral code {referral_code} applied successfully!",
    }


@agent.system_prompt
async def get_system_prompt(ctx: RunContext[OnboardingContext]) -> str:
    return ONBOARDING_PROMPT


def get_onboarding_agent():
    return agent
