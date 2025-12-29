from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from typing import Optional
import logging
import re

logger = logging.getLogger(__name__)

# Regex pattern to detect date-like phrases (used for conditional execution)
DATE_PATTERN = re.compile(
    r'\b(ago|past|last|next|previous|recent|upcoming|coming|'
    r'week|month|quarter|year|day|yesterday|tomorrow|tonight|'
    r'monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
    re.IGNORECASE
)


class DateReference(BaseModel):
    """A single date reference extracted from the message."""
    original_phrase: str = Field(description="The original phrase from the message, e.g., 'past 30 days'")
    start_date: str = Field(description="Start date in dd-mm-yyyy format")
    end_date: str = Field(description="End date in dd-mm-yyyy format (same as start_date for single dates)")


class DateContext(BaseModel):
    """Structured output containing all date references found in a message."""
    date_references: list[DateReference] = Field(
        default_factory=list,
        description="List of date references found in the message. Empty if no date references."
    )
    
    def to_context_string(self) -> Optional[str]:
        """Convert to a context string for the main agent, or None if no references."""
        if not self.date_references:
            return None
        
        lines = ["[DATE CONTEXT]"]
        for ref in self.date_references:
            if ref.start_date == ref.end_date:
                lines.append(f"• \"{ref.original_phrase}\" = {ref.start_date}")
            else:
                lines.append(f"• \"{ref.original_phrase}\" = {ref.start_date} to {ref.end_date}")
        return "\n".join(lines)


class PreprocessorContext(BaseModel):
    pass


agent = Agent(
    "mistral:mistral-small-latest",
    deps_type=PreprocessorContext,
    output_type=DateContext
)


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
async def calculate_date_from_days_ahead(ctx: RunContext[PreprocessorContext], days_ahead: int) -> str:
    """
    Calculate a date N days in the future from today in dd-mm-yyyy format.
    
    Args:
        days_ahead: Number of days in the future (e.g., 30 for "in 30 days", 7 for "next week")
        
    Returns:
        Date in dd-mm-yyyy format
    """
    logger.info(f"Tool called: calculate_date_from_days_ahead, days_ahead={days_ahead}")
    try:
        target_date = datetime.now() + timedelta(days=days_ahead)
        date_str = target_date.strftime("%d-%m-%Y")
        logger.info(f"Tool result: {days_ahead} days ahead = {date_str}")
        return date_str
    except Exception as e:
        error_msg = f"Error calculating date: {str(e)}"
        logger.error(f"Tool error: calculate_date_from_days_ahead - {error_msg}")
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
You are a date extraction agent for a financial AI assistant system.

Your ONLY job is to identify relative date/time references in messages and convert them to explicit dates.

You MUST output a structured DateContext with date references. You cannot answer questions or provide any other information.

INSTRUCTIONS:
1. Scan the message for relative date expressions (e.g., "past 30 days", "last week", "next quarter", "a few months ago")
2. Use the available tools to calculate explicit dates
3. Return a DateContext with all date references found
4. If there are NO relative date references, return an empty DateContext (date_references: [])

DATE INTERPRETATION GUIDELINES:
- "a few days" = approximately 3 days
- "a few weeks" = approximately 3 weeks (21 days)
- "a few months" = approximately 3 months (90 days)
- "a couple of X" = 2 of X
- "last week" = 7 days ago to today
- "last month" = 30 days ago to today
- "last quarter" = 90 days ago to today
- "next week" = today to 7 days from now
- "next month" = today to 30 days from now
- "next quarter" = today to 90 days from now
- "over the past X" = X days/weeks/months ago to today
- "over the next X" = today to X days/weeks/months from now

EXAMPLES:

Input: "how has ETH performed over the past 60 days?"
Output: DateContext with one reference:
  - original_phrase: "past 60 days"
  - start_date: [60 days ago]
  - end_date: [today]

Input: "what is the current price of Bitcoin?"
Output: DateContext with empty date_references (no relative dates)

Input: "compare performance from last month to next quarter"
Output: DateContext with two references:
  - original_phrase: "last month", start_date: [30 days ago], end_date: [today]
  - original_phrase: "next quarter", start_date: [today], end_date: [90 days from now]
"""


@agent.system_prompt
def get_system_prompt(ctx: RunContext[PreprocessorContext]) -> str:
    return PROMPT_TEMPLATE


def has_date_references(message: str) -> bool:
    """Check if a message likely contains date references (quick regex check)."""
    return bool(DATE_PATTERN.search(message))


def get_preprocessor_agent():
    return agent
