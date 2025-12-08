from pydantic_ai import Agent, RunContext
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class SummarizerContext(BaseModel):
    pass

agent = Agent("mistral:mistral-small-latest", deps_type=SummarizerContext)

PROMPT_TEMPLATE = """
You are an expert conversation archivist. Your goal is to summarize the following batch of conversation messages into a single, concise paragraph.

These messages are being moved to long-term storage. The summary you create will be used by the AI assistant in future interactions to recall what happened.

CRITICAL REQUIREMENTS:
1. Preserve key details about the user (name, preferences, goals, specific facts mentioned).
2. Capture the main topics discussed and any decisions made or actions taken.
3. Maintain chronological flow.
4. Be concise but comprehensive. Do not lose important context.
5. Do not include "User said" or "Assistant said" repeatedly. Write a narrative summary.
6. If the messages contain specific financial figures or investment choices, PRESERVE them exactly.

Format your response as a single paragraph of text of between 100 and 250 words.
"""

@agent.system_prompt
def get_system_prompt(ctx: RunContext[SummarizerContext]) -> str:
    return PROMPT_TEMPLATE

def get_summarizer_agent():
    return agent
