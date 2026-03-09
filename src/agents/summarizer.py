from pathlib import Path
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class SummarizerContext(BaseModel):
    pass

agent = Agent("mistral:mistral-small-latest", deps_type=SummarizerContext)

PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/summarizer.md").read_text()

@agent.system_prompt
def get_system_prompt(ctx: RunContext[SummarizerContext]) -> str:
    return PROMPT_TEMPLATE

def get_summarizer_agent():
    return agent
