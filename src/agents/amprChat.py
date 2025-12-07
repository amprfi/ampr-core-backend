from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
from convex import ConvexClient
from typing import List, Dict
import logging

from pydantic_ai.agent.abstract import RunOutputDataT
from src.models.user_profile import UserProfile
from src.utils.preprocessing import profile_to_sentences

logger = logging.getLogger(__name__)

class TalkerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str

agent = Agent("mistral:mistral-large", deps_type=TalkerContext)

@agent.tool
async def get_user_country_tool(ctx: RunContext[TalkerContext]) -> str:
    """
    Get the current user's 3-letter country code for location-specific answers.
    """
    logger.info(f"Tool called: get_user_country_tool for user_id={ctx.deps.user_id}")
    try:
        result = ctx.deps.convex_client.query("profiles:getUserCountry", {
            "userId": ctx.deps.user_id
        })
        country = result.get("country") if result else "Unknown"
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
        result = ctx.deps.convex_client.query("profiles:getInvestmentPreferences", {
            "userId": ctx.deps.user_id
        })

        if not result:
            logger.warning("No profile data found")
            return ["No investment preferences found for this user."]

        profile_data = UserProfile(
            country=None,
            kyc_passed=False,
            stated_investment_horizon=result.get("stated_investment_horizon"),
            stated_risk_appetite=result.get("stated_risk_appetite"),
            stated_investment_knowledge=result.get("stated_investment_knowledge"),
            stated_financial_goals=result.get("stated_financial_goals"),
            
            other_investments=result.get("other_investments"),
            
            inferred_investment_horizon=result.get("inferred_investment_horizon"),
            inferred_risk_appetite=result.get("inferred_risk_appetite"),
            inferred_investment_knowledge=result.get("inferred_investment_knowledge"),
            inferred_financial_goals=result.get("inferred_financial_goals"),
            inferred_investment_thesis=result.get("inferred_investment_thesis")
        )

        sentences = profile_to_sentences(profile_data)
        logger.info(f"Tool result: user_investment_preferences returned {len(sentences)} sentences")
        return sentences
    except Exception as e:
        error_msg = f"Error retrieving preferences: {str(e)}"
        logger.error(f"Tool error: user_investment_preferences - {error_msg}")
        return [error_msg]

PROMPT_TEMPLATE = """
You are a helpful, conversational AI assistant for Ampersand, the first open financial operating system.

Ampersand is a complete financial portal that combines a web3 wallet, an intelligent AI co-pilot, and an app store filled with various financial products, strategies, and agents.

TONE & STYLE:
- Be natural, friendly, and conversational
- Keep responses concise (aim for 2-3 sentences when possible)
- Use plain text only - no Markdown formatting (**, *, _, etc.), no bullet points, no headers
- Do not mention the user's preferences, goals, or background information back to them

TOOLS:
- When you need the user's country for location-specific information, use get_user_country_tool (returns ISO 3166-1 alpha-3 code)
- When you need the user's investment preferences and goals, use user_investment_preferences_tool

CONTENT RESTRICTIONS:
If there is a [MODULE RESPONSE] section:
- Present the data naturally and conversationally
- Preserve all numbers, dates, and factual information exactly
- Transform formatting into natural sentences (e.g., turn bullet points into prose)

If there is NO [MODULE RESPONSE] section, you MUST NOT provide:
- Price or market data on any assets (stocks, bonds, currencies, crypto-tokens)
- Investment or portfolio recommendations

"""

@agent.system_prompt
async def get_system_prompt(ctx: RunContext[TalkerContext]) -> str:
    return PROMPT_TEMPLATE

def get_amprChat_agent():
    return agent
