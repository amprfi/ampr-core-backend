from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from convex import ConvexClient
import logging

logger = logging.getLogger(__name__)

class ExtractorContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str

class ExtractedProfile(BaseModel):
    inferred_investment_horizon: Optional[str] = Field(
        None,
        description="Investment timeframe: E_1_5 (short-term), E_6_10 (medium-term), E_10_20 (long-term), or E_20PLUS (very long-term)"
    )
    inferred_risk_appetite: Optional[int] = Field(
        None,
        ge=1,
        le=5,
        description="Risk tolerance from 1 (very conservative) to 5 (very aggressive)"
    )
    inferred_investment_knowledge: Optional[str] = Field(
        None,
        description="Investment expertise: NOVICE, INTERMEDIATE, or ADVANCED"
    )
    inferred_financial_goals: Optional[List[str]] = Field(
        None,
        description="List of financial goals mentioned (e.g., 'retirement', 'home purchase', 'wealth building')"
    )
    inferred_investment_thesis: Optional[str] = Field(
        None,
        description="User's overall investment philosophy or thesis synthesized from conversations"
    )

agent = Agent(
    "mistral:mistral-small-latest",
    deps_type=ExtractorContext,
    output_type=ExtractedProfile
)

@agent.tool
async def get_current_profile(ctx: RunContext[ExtractorContext]) -> str:
    """
    Get the current inferred profile data for this user to avoid contradictions.
    """
    logger.info(f"Tool called: get_current_profile for user_id={ctx.deps.user_id}")
    try:
        result = ctx.deps.convex_client.query("profiles:getInvestmentPreferences", {
            "userId": ctx.deps.user_id
        })
        
        if not result:
            return "No existing profile data found. All fields are empty."
        
        profile_summary = []
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
        
        if not profile_summary:
            return "No existing inferred profile data. All fields are empty."
        
        logger.info(f"Tool result: get_current_profile returned {len(profile_summary)} fields")
        return "\n".join(profile_summary)
    except Exception as e:
        error_msg = f"Error retrieving current profile: {str(e)}"
        logger.error(f"Tool error: get_current_profile - {error_msg}")
        return error_msg

PROMPT_TEMPLATE = """
You are an expert financial profiler. Your task is to analyze conversation messages and extract implicit information about the user's investment profile.

CRITICAL REQUIREMENTS:
1. ALWAYS call get_current_profile first to see what's already known about the user.
2. Only extract information when there is CLEAR EVIDENCE in the messages.
3. Do not make assumptions or guesses. Return null for fields where evidence is weak or absent.
4. Be conservative - it's better to extract nothing than to extract incorrect information.
5. Consider existing profile data to avoid contradictions.

FIELD DEFINITIONS:

**inferred_investment_horizon**
- Evidence: User mentions timeframes ("saving for retirement in 30 years", "need money in 2 years", "long-term growth")
- Values: E_1_5 (short-term), E_6_10 (medium-term), E_10_20 (long-term), E_20PLUS (very long-term)
- Example: "I'm 25 and thinking about retirement" → E_20PLUS

**inferred_risk_appetite** (1-5 scale)
- 1: Very conservative (mentions safety, capital preservation, can't afford losses)
- 2: Conservative (prefers stability, mentions bonds/stable assets)
- 3: Moderate (balanced approach, mentions diversification)
- 4: Aggressive (seeks growth, comfortable with volatility)
- 5: Very aggressive (mentions high-risk assets, speculation, maximizing returns)
- Example: "I can handle some volatility for better returns" → 3 or 4

**inferred_investment_knowledge**
- NOVICE: Basic questions, unfamiliar with investment concepts, asks for explanations
- INTERMEDIATE: Understands basic concepts, asks about specific strategies, familiar with common assets
- ADVANCED: Discusses complex strategies, derivatives, portfolio optimization, risk management
- Example: "What's the difference between stocks and bonds?" → NOVICE

**inferred_financial_goals**
- Extract specific goals mentioned: "retirement", "buying a home", "children's education", "wealth building", "passive income", etc.
- Only include goals explicitly or clearly implied in messages
- Return as array of goal strings
- MERGE with existing goals if present (don't overwrite, add new ones)

**inferred_investment_thesis**
- A concise summary (1-2 sentences) of the user's overall investment philosophy
- Only populate if user has expressed clear views about their approach
- Example: "Believes in long-term index fund investing with minimal active trading"
- Return null unless there's substantial evidence
- If updating existing thesis, refine or expand it based on new information

If existing profile has inferred values, only update them if new evidence contradicts or adds significant detail.
"""

@agent.system_prompt
def get_system_prompt(ctx: RunContext[ExtractorContext]) -> str:
    return PROMPT_TEMPLATE

def get_extractor_agent():
    return agent
