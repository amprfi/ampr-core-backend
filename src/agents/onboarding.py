from pathlib import Path
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
from convex import ConvexClient
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

class OnboardingContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str
    telegram_id: Optional[str] = None

agent = Agent(
    "mistral:mistral-large-latest",
    deps_type=OnboardingContext,
    output_type=List[str]
)

@agent.tool
async def get_user_info(ctx: RunContext[OnboardingContext]) -> dict:
    """
    Get the current user's information from the database to see what's already filled in.
    Returns user fields like first_name, last_name, email, phone, telegram_id.
    """
    logger.info(f"Tool called: get_user_info for user_id={ctx.deps.user_id}")
    try:
        user = ctx.deps.convex_client.query("users:getUser", {"userId": ctx.deps.user_id})
        if not user:
            raise ValueError(f"User {ctx.deps.user_id} not found")
        
        logger.info(f"Tool result: get_user_info returned user data")
        return {
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "telegram_id": user.get("telegram_id")
        }
    except Exception as e:
        error_msg = f"Error retrieving user info: {str(e)}"
        logger.error(f"Tool error: get_user_info - {error_msg}")
        return {"error": error_msg}

@agent.tool
async def update_user_info(
    ctx: RunContext[OnboardingContext],
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    telegram_id: Optional[str] = None
) -> str:
    """
    Update the user's information in the database.
    Only provide the fields you want to update.
    Returns success message or error.
    """
    logger.info(f"Tool called: update_user_info for user_id={ctx.deps.user_id}")
    try:
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
        
        ctx.deps.convex_client.mutation("users:updateUser", {
            "id": ctx.deps.user_id,
            **update_data
        })
        
        logger.info(f"Tool result: update_user_info updated fields: {list(update_data.keys())}")
        return f"Successfully updated: {', '.join(update_data.keys())}"
    except Exception as e:
        error_msg = f"Error updating user info: {str(e)}"
        logger.error(f"Tool error: update_user_info - {error_msg}")
        return error_msg

@agent.tool
async def set_user_country(
    ctx: RunContext[OnboardingContext],
    country_name: str
) -> str:
    """
    Set the user's country on their profile.
    Accepts a country name (e.g., "United States", "Germany") or ISO 3166-1 alpha-3 code (e.g., "USA", "DEU").
    Looks up the country in the database and updates the user's profile.
    """
    logger.info(f"Tool called: set_user_country for user_id={ctx.deps.user_id}, country_name={country_name}")
    try:
        # Try looking up by code first (uppercase)
        country = ctx.deps.convex_client.query("countries:getCountryByCode", {
            "country_code": country_name.upper()
        })

        if not country:
            # Search all countries by name (case-insensitive partial match)
            all_countries = ctx.deps.convex_client.query("countries:getCountries", {})
            for c in all_countries:
                if country_name.lower() in c["country_name"].lower():
                    country = c
                    break

        if not country:
            return f"Could not find country '{country_name}'. Please try again with the full country name or 3-letter code."

        # Upsert the profile with the country
        ctx.deps.convex_client.mutation("profiles:updateProfile", {
            "user": ctx.deps.user_id,
            "country": country["_id"]
        })

        logger.info(f"Tool result: set_user_country set country to {country['country_name']} ({country['country_code']})")
        return f"Country set to {country['country_name']}"
    except Exception as e:
        error_msg = f"Error setting country: {str(e)}"
        logger.error(f"Tool error: set_user_country - {error_msg}")
        return error_msg

@agent.tool
async def complete_onboarding(ctx: RunContext[OnboardingContext]) -> str:
    """
    Mark the user's onboarding as complete.
    Call this when the user has provided their name OR declined to provide additional info.
    """
    logger.info(f"Tool called: complete_onboarding for user_id={ctx.deps.user_id}")
    try:
        ctx.deps.convex_client.mutation("users:updateUser", {
            "id": ctx.deps.user_id,
            "onboarding_complete": True
        })
        logger.info(f"Tool result: Onboarding marked complete for user {ctx.deps.user_id}")
        return "Onboarding marked as complete"
    except Exception as e:
        error_msg = f"Error completing onboarding: {str(e)}"
        logger.error(f"Tool error: complete_onboarding - {error_msg}")
        return error_msg

ONBOARDING_PROMPT = (Path(__file__).parent / "prompts/onboarding.md").read_text()

@agent.system_prompt
async def get_system_prompt(ctx: RunContext[OnboardingContext]) -> str:
    return ONBOARDING_PROMPT

def get_onboarding_agent():
    return agent
