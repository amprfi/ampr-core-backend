from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
from gel import AsyncIOClient

class TalkerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    gel_client: AsyncIOClient

agent = Agent("mistral:mistral-medium", deps_type=TalkerContext)

# Simplified system prompt without user information and preferences to be added later
PROMPT_TEMPLATE = """
You are a helpful assistant that can answer questions and help with tasks for Ampersand, the first open financial operating system.

Ampersand is a complete financial portal that combines a web3 wallet, an intelligent AI co-pilot, and an app store filled with various financial products, strategies, and agents.

Keep your responses relatively concise--less than 150 characters per message.
"""

@agent.system_prompt
async def get_system_prompt(context: RunContext[TalkerContext]):
    return PROMPT_TEMPLATE

# Dependency function to get the agent
def get_amprChat_agent():
    return agent