from pydantic_ai import Agent, RunContext
from pydantic import BaseModel
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class PreprocessorContext(BaseModel):
    pass


agent = Agent("mistral:mistral-small", deps_type=PreprocessorContext)


@agent.tool
async def calculate_date_from_days_ago(ctx: RunContext[PreprocessorContext], days_ago: int) -> str:
    """
    Calculate a date N days ago from today in dd-mm-yyyy format.
    
    Args:
        days_ago: Number of days ago (e.g., 30 for "30 days ago", 7 for "a week ago")
        
    Returns:
        Date in dd-mm-yyyy format
    """
    logger.info(f"Tool called: calculate_date_from_days_ago, days_ago={days_ago}")
    try:
        target_date = datetime.now() - timedelta(days=days_ago)
        date_str = target_date.strftime("%d-%m-%Y")
        logger.info(f"Tool result: {days_ago} days ago = {date_str}")
        return date_str
    except Exception as e:
        error_msg = f"Error calculating date: {str(e)}"
        logger.error(f"Tool error: calculate_date_from_days_ago - {error_msg}")
        return error_msg


@agent.tool
async def get_current_date(ctx: RunContext[PreprocessorContext]) -> str:
    """
    Get today's date in dd-mm-yyyy format.
    
    Returns:
        Today's date in dd-mm-yyyy format
    """
    logger.info("Tool called: get_current_date")
    try:
        date_str = datetime.now().strftime("%d-%m-%Y")
        logger.info(f"Tool result: current date = {date_str}")
        return date_str
    except Exception as e:
        error_msg = f"Error getting current date: {str(e)}"
        logger.error(f"Tool error: get_current_date - {error_msg}")
        return error_msg


PROMPT_TEMPLATE = """
You are a message preprocessor for a financial AI assistant system.

Your ONLY job is to convert relative date/time references into explicit dates in dd-mm-yyyy format.

CRITICAL RULES:
1. Preserve ALL original message content except date references
2. Only modify relative date expressions (e.g., "past 30 days", "last week", "over the past 2 months")
3. Convert relative dates to explicit dates using the available tools
4. Return the modified message with dates in dd-mm-yyyy format
5. If there are NO relative date references, return the message EXACTLY as-is
6. Do NOT add explanations, do NOT add extra text, do NOT remove content

EXAMPLES:

Input: "@defianalyst how has ETH performed relative to SOL over the past 60 days?"
Output: "@defianalyst how has ETH performed relative to SOL from 08-10-2025 to 08-12-2025?"

Input: "@defianalyst compare Bitcoin and Ethereum performance over the last 3 months"
Output: "@defianalyst compare Bitcoin and Ethereum performance from 08-09-2025 to 08-12-2025"

Input: "@defianalyst what is the current price of Bitcoin?"
Output: "@defianalyst what is the current price of Bitcoin?"
(no change - no relative dates)

Input: "How did Solana perform in the past week compared to today?"
Output: "How did Solana perform from 01-12-2025 to 08-12-2025?"

PROCESS:
1. Identify if the message contains relative date references
2. If yes, use calculate_date_from_days_ago and/or get_current_date to get explicit dates
3. Replace the relative reference with explicit dates
4. Return the modified message
5. If no relative dates, return original message unchanged
"""


@agent.system_prompt
def get_system_prompt(ctx: RunContext[PreprocessorContext]) -> str:
    return PROMPT_TEMPLATE


def get_preprocessor_agent():
    return agent
