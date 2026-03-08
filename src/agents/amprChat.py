from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
from convex import ConvexClient
from typing import List, Dict
import logging

from pydantic_ai.agent.abstract import RunOutputDataT
from src.models.user_profile import UserProfile
from src.utils.preprocessing import profile_to_sentences
from src.modules.registry import get_module_registry

logger = logging.getLogger(__name__)

class TalkerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str
    date_context: str | None = None
    invoked_modules: list[str] = []
    module_already_invoked: bool = False  # True if &mention already triggered a module

agent = Agent(
    "mistral:mistral-large-latest",
    deps_type=TalkerContext,
    output_type=List[str]
)

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

@agent.tool
async def list_specialist_modules(ctx: RunContext[TalkerContext]) -> List[Dict[str, str]]:
    """
    List all available specialist modules with their names and descriptions.
    Use this when deciding which module best fits a user's request.
    """
    logger.info("Tool called: list_specialist_modules")
    registry = get_module_registry()
    modules = registry.list_modules()
    logger.info(f"Tool result: list_specialist_modules returned {len(modules)} modules")
    return modules

@agent.tool
async def call_specialist_module(
    ctx: RunContext[TalkerContext],
    module_name: str,
    question: str,
) -> str:
    """
    Call a specialist financial module when you need live or detailed data.

    Args:
        module_name: The module to call. Available modules:
            - "defianalyst": Cryptocurrency & token market data (prices, market caps, volumes, historical data)
            - "oracle": Prediction market prices & probabilities (Polymarket data)
        question: A focused description of what you want the module to answer,
            derived from the user's request.

    Returns:
        The module's response with the requested data.
    """
    logger.info(f"Tool called: call_specialist_module for module={module_name}")

    if ctx.deps.module_already_invoked:
        logger.info("Module already invoked via &mention, skipping tool call")
        return "A specialist module has already been invoked for this request. Use the data from [MODULE RESPONSE] instead."

    registry = get_module_registry()
    module = registry.get_module(module_name)

    if not module:
        available = [m["name"] for m in registry.list_modules()]
        error_msg = f"Unknown module '{module_name}'. Available modules: {', '.join(available)}"
        logger.warning(f"Tool error: call_specialist_module - {error_msg}")
        return f"ERROR: {error_msg}"

    try:
        result = await registry.invoke_module(
            module_name,
            message=question,
            date_context=ctx.deps.date_context,
        )

        if module_name not in ctx.deps.invoked_modules:
            ctx.deps.invoked_modules.append(module_name)

        logger.info(f"Tool result: call_specialist_module for {module_name} succeeded")
        return result
    except Exception as e:
        error_msg = f"Module '{module_name}' failed: {str(e)}"
        logger.error(f"Tool error: call_specialist_module - {error_msg}", exc_info=True)
        return f"ERROR: {error_msg}"

PROMPT_TEMPLATE = """
You are a helpful, conversational AI assistant for Ampersand, the first open financial operating system.

Ampersand is a complete financial portal that combines a web3 wallet, an intelligent AI co-pilot, and an app store filled with various financial products, strategies, and agents.

TONE & STYLE:
- Be natural, friendly, and conversational
- Keep responses concise (aim for 2-3 sentences when possible)
- You may use Markdown formatting (bold, italic, etc.) where it improves readability
- Do not mention the user's preferences, goals, or background information back to them

TOOLS:
- get_user_country_tool: Get the user's country for location-specific information (returns ISO 3166-1 alpha-3 code)
- user_investment_preferences: Get the user's investment preferences and goals
- call_specialist_module: Call a specialist module for live financial data. Use this when you need:
  - Cryptocurrency/token prices, market caps, volumes, or historical data → use module "defianalyst"
  - Future prices for assets or probabilities of various finanical or economic events → use module "oracle"
- list_specialist_modules: List all available specialist modules if you're unsure which to use

SPECIALIST MODULES:
You have access to specialist modules that provide real-time financial data. When a user asks about:
- Crypto prices, market caps, top performers, historical prices → call "defianalyst" module
- Future prices for assets or probabilities of various finanical or economic events → call "oracle" module

CONTENT RESTRICTIONS:
If there is a [MODULE RESPONSE] section (from an &mention trigger):
- A specialist module has already been invoked - DO NOT call call_specialist_module again
- Present the data naturally and conversationally
- Preserve all numbers, dates, and factual information exactly
- Transform formatting into natural sentences (e.g., turn bullet points into prose)

If there is NO [MODULE RESPONSE] section:
- You MUST use call_specialist_module to get any live price, market, or probability data
- You MUST NOT invent or guess prices, volumes, market caps, or probabilities
- If the module fails or is unavailable, tell the user you cannot retrieve that data right now

MODULE ATTRIBUTION:
- When your answer is based on data from a specialist module, briefly mention it once using the format "via &[module]"
- Example: "Via &defianalyst, Bitcoin is currently trading at $50,000."
- Don't repeat the attribution for follow-up details from the same module call

RESPONSE FORMAT:
- Return your response as a list of messages
- You can break up longer responses into multiple messages for a more natural conversation flow
- Example: ["Here's what I found.", "Bitcoin is currently trading at $50,000."]
- Each string in the list will be sent as a separate message to the user
"""

@agent.system_prompt
async def get_system_prompt(ctx: RunContext[TalkerContext]) -> str:
    return PROMPT_TEMPLATE

def get_amprChat_agent():
    return agent
