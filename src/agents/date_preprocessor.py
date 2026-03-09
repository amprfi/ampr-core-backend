from pathlib import Path
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


class DatePreprocessorContext(BaseModel):
    pass


agent = Agent(
    "mistral:mistral-small-latest",
    deps_type=DatePreprocessorContext,
    output_type=DateContext
)


@agent.tool
async def calculate_date_from_days_ago(ctx: RunContext[DatePreprocessorContext], days_ago: int) -> str:
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
async def calculate_date_from_days_ahead(ctx: RunContext[DatePreprocessorContext], days_ahead: int) -> str:
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
async def get_current_date(ctx: RunContext[DatePreprocessorContext]) -> str:
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


PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/date_preprocessor.md").read_text()


@agent.system_prompt
def get_system_prompt(ctx: RunContext[DatePreprocessorContext]) -> str:
    return PROMPT_TEMPLATE


def has_date_references(message: str) -> bool:
    """Check if a message likely contains date references (quick regex check)."""
    return bool(DATE_PATTERN.search(message))


def get_date_preprocessor_agent():
    return agent
