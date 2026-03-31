from pathlib import Path
from pydantic import BaseModel, Field
from datetime import datetime, date
from calendar import monthrange
from typing import Optional
import httpx
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MODEL = "mistral-small-latest"

# Regex pattern to detect date-like phrases (used for conditional execution)
DATE_PATTERN = re.compile(
    r'\b(ago|past|last|next|previous|recent|upcoming|coming|'
    r'week|month|quarter|year|day|yesterday|tomorrow|tonight|'
    r'monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
    re.IGNORECASE
)

PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/date_preprocessor.md").read_text()


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


class _DatePreprocessorResult:
    """Wrapper to maintain interface compatibility with pydantic-ai's RunResult."""
    def __init__(self, output: DateContext):
        self.output = output


def _build_calendar_context(today: date) -> str:
    """Build calendar context with quarter and month boundaries."""
    # Quarter boundaries (Q1: Jan-Mar, Q2: Apr-Jun, Q3: Jul-Sep, Q4: Oct-Dec)
    quarter_starts = {1: 1, 2: 4, 3: 7, 4: 10}
    quarter_ends = {1: 3, 2: 6, 3: 9, 4: 12}

    current_q = (today.month - 1) // 3 + 1
    prev_q = current_q - 1 if current_q > 1 else 4
    next_q = current_q + 1 if current_q < 4 else 1
    prev_q_year = today.year if current_q > 1 else today.year - 1
    next_q_year = today.year if current_q < 4 else today.year + 1

    def q_range(q: int, year: int) -> str:
        start = date(year, quarter_starts[q], 1)
        end_month = quarter_ends[q]
        end_day = monthrange(year, end_month)[1]
        end = date(year, end_month, end_day)
        return f"{start.strftime('%d-%m-%Y')} to {end.strftime('%d-%m-%Y')}"

    # Previous, current, next month boundaries
    prev_month = today.month - 1 if today.month > 1 else 12
    prev_month_year = today.year if today.month > 1 else today.year - 1
    prev_month_last_day = monthrange(prev_month_year, prev_month)[1]
    next_month = today.month + 1 if today.month < 12 else 1
    next_month_year = today.year if today.month < 12 else today.year + 1
    next_month_last_day = monthrange(next_month_year, next_month)[1]

    fmt = "%d-%m-%Y"
    lines = [
        f"Today's date: {today.strftime('%A, %B %d, %Y')}",
        "",
        "CALENDAR CONTEXT:",
        f"Current quarter (Q{current_q}): {q_range(current_q, today.year)}",
        f"Previous quarter (Q{prev_q}): {q_range(prev_q, prev_q_year)}",
        f"Next quarter (Q{next_q}): {q_range(next_q, next_q_year)}",
        f"Current month: {date(today.year, today.month, 1).strftime(fmt)} to {date(today.year, today.month, monthrange(today.year, today.month)[1]).strftime(fmt)}",
        f"Previous month: {date(prev_month_year, prev_month, 1).strftime(fmt)} to {date(prev_month_year, prev_month, prev_month_last_day).strftime(fmt)}",
        f"Next month: {date(next_month_year, next_month, 1).strftime(fmt)} to {date(next_month_year, next_month, next_month_last_day).strftime(fmt)}",
    ]
    return "\n".join(lines)


class DatePreprocessorAgent:
    """Date preprocessor using direct Mistral API calls with reasoning."""

    async def run(self, message: str, deps: DatePreprocessorContext = None) -> _DatePreprocessorResult:
        calendar_context = _build_calendar_context(date.today())
        system_prompt = f"{calendar_context}\n\n{PROMPT_TEMPLATE}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]

        body = {
            "model": MODEL,
            "messages": messages,
            "reasoning_effort": "high",
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    MISTRAL_API_URL,
                    headers={
                        "Authorization": f"Bearer {MISTRAL_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()

            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            date_context = DateContext(**parsed)
            logger.info(f"Date preprocessor resolved {len(date_context.date_references)} reference(s)")
            return _DatePreprocessorResult(output=date_context)

        except Exception as e:
            logger.error(f"Date preprocessor error: {e}", exc_info=True)
            return _DatePreprocessorResult(output=DateContext())


def has_date_references(message: str) -> bool:
    """Check if a message likely contains date references (quick regex check)."""
    return bool(DATE_PATTERN.search(message))


def get_date_preprocessor_agent():
    return DatePreprocessorAgent()
