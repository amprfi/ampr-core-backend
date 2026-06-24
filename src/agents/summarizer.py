from pathlib import Path
import logging

from .mistral_helpers import (
    get_shared_client,
    build_messages,
    extract_text_from_content,
    MODEL_MEDIUM,
)

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = (Path(__file__).parent / "prompts/summarizer.md").read_text()


class SummarizerAgent:
    """
    Summarizer agent using Mistral SDK.

    Replaces the previous pydantic-ai Agent with a direct Mistral SDK call.
    """

    def __init__(self):
        self.client = get_shared_client()
        self.system_prompt = PROMPT_TEMPLATE

    async def run(self, message: str) -> str:
        """
        Run the summarizer on the given message.

        Args:
            message: The message/content to summarize

        Returns:
            The summary text as a string
        """
        messages = build_messages(self.system_prompt, message)

        try:
            response = await self.client.chat.complete_async(
                model=MODEL_MEDIUM,
                messages=messages,
                temperature=0.3,
                reasoning_effort="none",
            )

            content = response.choices[0].message.content
            summary = extract_text_from_content(content)

            logger.info(f"Summarizer generated summary of length {len(summary)}")
            return summary

        except Exception as e:
            logger.error(f"Summarizer failed: {e}", exc_info=True)
            # Graceful fallback: return empty string to match other agents
            return ""


# Singleton instance
_agent_instance: SummarizerAgent | None = None


def get_summarizer_agent() -> SummarizerAgent:
    """
    Get a summarizer agent instance.

    Returns:
        Singleton SummarizerAgent instance
    """
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = SummarizerAgent()
    return _agent_instance
