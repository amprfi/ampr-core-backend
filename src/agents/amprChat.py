"""
AmprChat agent using Mistral SDK tool runner.

This module provides the main amprChat agent for backend chat, now migrated
from pydantic-ai to the Mistral SDK tool runner (see AMPRFI-117).

Key changes from the original pydantic-ai implementation:
- Uses tool_runner.py for streaming-native tool execution
- Tools use Pydantic args models for validation (see amprchat_tools.py)
- currency_context is injected into the per-turn context string alongside
  date_context in build_context_string(), not appended to the system prompt
- Preserves all existing behavior and tool functionality
"""

import logging
from typing import AsyncIterator, Optional

from convex import ConvexClient
from pydantic import BaseModel, ConfigDict

from src.agents.amprchat_tools import build_amprchat_config, build_help_overview
from src.agents.tool_runner import run as tool_runner_run
from src.agents.tool_runner import run_stream as tool_runner_stream

logger = logging.getLogger(__name__)


# =============================================================================
# TalkerContext
# =============================================================================

class TalkerContext(BaseModel):
    """
    Context passed to amprChat tools and runner.

    Contains all runtime information needed for tool execution and response generation.
    This is the same model used by the original pydantic-ai implementation for
    backward compatibility with existing callers.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    convex_client: ConvexClient
    user_id: str
    date_context: Optional[str] = None
    invoked_modules: list[str] = []
    channel: Optional[str] = None
    telegram_id: Optional[str] = None


# =============================================================================
# Compatibility Shim for Existing Callers
# =============================================================================

class AmprChatAgent:
    """
    Compatibility shim that provides the same interface as the original
    pydantic_ai.Agent for amprChat.

    This allows existing callers in web.py and telegram.py to continue using:
        agent = get_amprChat_agent()
        result = await agent.run(context_str, deps=talker_context)

    The shim translates these calls to use the new Mistral SDK runner.
    """

    def __init__(self):
        """Initialize the compatibility shim."""

    async def run(self, user_message: str, deps: TalkerContext) -> "AgentRunResult":
        """
        Run the amprChat agent with the given user message and dependencies.

        This is the main entry point for non-streaming execution, matching the
        original pydantic_ai.Agent.run() signature.

        Args:
            user_message: The user message / context string
            deps: TalkerContext containing runtime context

        Returns:
            AgentRunResult with the output text
        """
        config = await build_amprchat_config(deps)
        output = await tool_runner_run(config, user_message)
        return AgentRunResult(output=output)

    async def stream(self, user_message: str, deps: TalkerContext) -> AsyncIterator[str]:
        """
        Stream the amprChat agent response for the given user message.

        This provides token-level streaming for backend use (see AMPRFI-114).

        Args:
            user_message: The user message / context string
            deps: TalkerContext containing runtime context

        Yields:
            Text deltas as they are generated
        """
        config = await build_amprchat_config(deps)
        async for delta in tool_runner_stream(config, user_message):
            yield delta


class AgentRunResult:
    """
    Compatibility result object matching pydantic_ai's AgentRunResult interface.

    Provides the .output attribute that existing callers expect.
    """

    def __init__(self, output: str):
        self.output = output


# =============================================================================
# Module-Level Functions (for direct imports)
# =============================================================================

def get_amprChat_agent() -> AmprChatAgent:
    """
    Get the amprChat agent instance.

    Returns a compatibility shim that provides the same interface as the
    original pydantic_ai.Agent, but uses the Mistral SDK runner internally.

    Returns:
        AmprChatAgent instance
    """
    return AmprChatAgent()
