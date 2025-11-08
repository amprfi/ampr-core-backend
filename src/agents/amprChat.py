from pydantic_ai import Agent, RunContext
from pydantic import BaseModel, ConfigDict
from gel import AsyncIOClient
import uuid
from src.queries.memory.get_user_country_async_edgeql import get_user_country

class TalkerContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    gel_client: AsyncIOClient
    user_id: uuid.UUID

agent = Agent("mistral:mistral-medium", deps_type=TalkerContext)

@agent.tool
async def get_user_country_tool(ctx: RunContext[TalkerContext]) -> str:
    """
    Get the current user's country for location-specific answers.
    """
    try:
        result = await get_user_country(
            executor=ctx.deps.gel_client,
            user_id=ctx.deps.user_id
        )
        return result.country if result else "Unknown"
    except Exception as e:
        return f"Error retrieving country: {str(e)}"

# Simplified system prompt without user information and preferences to be added later
PROMPT_TEMPLATE = """
You are a helpful assistant that can answer questions and help with tasks for Ampersand, the first open financial operating system.

Ampersand is a complete financial portal that combines a web3 wallet, an intelligent AI co-pilot, and an app store filled with various financial products, strategies, and agents.

Keep your responses relatively concise--less than 150 characters per message.

When you need to know the user's country for location-specific information (like regulations, available services, or financial products), use the get_user_country_tool.

"""

@agent.system_prompt
async def get_system_prompt(ctx: RunContext[TalkerContext]) -> str:
    return PROMPT_TEMPLATE

def get_amprChat_agent():
    return agent