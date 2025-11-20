from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
from gel import AsyncIOClient
from typing import List, Dict
import uuid
import logging

from pydantic_ai.agent.abstract import RunOutputDataT
from src.queries.memory.get_user_country_async_edgeql import get_user_country
from src.queries.memory.get_user_investment_preferences_async_edgeql import get_user_investment_preferences
from src.models.user_profile import UserProfile
from src.utils.preprocessing import profile_to_sentences

logger = logging.getLogger(__name__)

class TalkerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    gel_client: AsyncIOClient
    user_id: uuid.UUID

agent = Agent("mistral:mistral-medium", deps_type=TalkerContext)

@agent.tool
async def get_user_country_tool(ctx: RunContext[TalkerContext]) -> str:
    """
    Get the current user's 3-letter country code for location-specific answers.
    """
    logger.info(f"Tool called: get_user_country_tool for user_id={ctx.deps.user_id}")
    try:
        result = await get_user_country(
            executor=ctx.deps.gel_client,
            user_id=ctx.deps.user_id
        )
        country = result.country if result else "Unknown"
        logger.info(f"Tool result: get_user_country_tool returned '{country}'")
        return country
    except Exception as e:
        error_msg = f"Error retrieving country: {str(e)}"
        logger.error(f"Tool error: get_user_country_tool - {error_msg}")
        return error_msg

@agent.tool
async def user_investment_preferences(ctx: RunContext[TalkerContext]) -> List[str]:
    """
    Get the user's investment preferences and background information.
    """
    logger.info(f"Tool called: user_investment_preferences for user_id={ctx.deps.user_id}")
    try:
        result = await get_user_investment_preferences(
            executor=ctx.deps.gel_client,
            user_id=ctx.deps.user_id
        )

        if not result:
            logger.warning("No profile data found")
            return ["No investment preferences found for this user."]

        profile_data = UserProfile(
            country=None,
            kyc_passed=False,
            investment_horizon=result.investment_horizon.value if result.investment_horizon else None,
            age_group=result.age_group.value if result.age_group else None,
            risk_appetite=result.risk_appetite,
            reason_for_investing=result.reason_for_investing,
            other_investments=result.other_investments,
            investment_knowledge=result.investment_knowledge.value if result.investment_knowledge else None,
            financial_goals=result.financial_goals
        )

        sentences = profile_to_sentences(profile_data)
        logger.info(f"Tool result: user_investment_preferences returned {len(sentences)} sentences")
        return sentences
    except Exception as e:
        error_msg = f"Error retrieving preferences: {str(e)}"
        logger.error(f"Tool error: user_investment_preferences - {error_msg}")
        return [error_msg]

PROMPT_TEMPLATE = """
You are a helpful assistant that can answer questions and help with tasks for Ampersand, the first open financial operating system.

Ampersand is a complete financial portal that combines a web3 wallet, an intelligent AI co-pilot, and an app store filled with various financial products, strategies, and agents.

Keep your responses relatively concise--less than 150 characters per message. Do not mention the user's own preferences, goals, or background information back to them.

You have access to tools obtain information about the user's financial background, preferences, and location.

- When you need to know the user's country for location-specific information (like regulations, available services, or financial products), use the get_user_country_tool, it will return the ISO 3166-1 alpha-3 country code.

- When you need to know the user's investment preferences and goals, use the user_investment_preferences_tool, it will return a list of the user's investment preferences and background information.

"""

@agent.system_prompt
async def get_system_prompt(ctx: RunContext[TalkerContext]) -> str:
    return PROMPT_TEMPLATE

def get_amprChat_agent():
    return agent
