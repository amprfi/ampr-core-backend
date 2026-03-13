"""
Notification synthesizer.

Uses an LLM to combine multiple pending notifications from the same module
into a single coherent message for delivery to the user.
"""
import logging
from pydantic_ai import Agent

logger = logging.getLogger(__name__)

_synthesizer_agent = Agent(
    "mistral:mistral-small-latest",
    output_type=str,
    system_prompt=(
        "You combine multiple notification messages into a single concise, "
        "coherent notification for the user. Preserve all important information "
        "(asset names, prices, percentages, thresholds) but eliminate redundancy. "
        "Use a natural, conversational tone. Do not add greetings or sign-offs. "
        "If the notifications are about different assets, organize by asset. "
        "Keep the combined message as brief as possible while retaining all "
        "key data points."
    ),
)


async def synthesize_notifications(contents: list[str]) -> str:
    """
    Combine multiple notification messages into one.

    Args:
        contents: List of individual notification content strings.

    Returns:
        A single synthesized message string.
    """
    if len(contents) == 1:
        return contents[0]

    numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(contents))
    prompt = (
        f"Combine these {len(contents)} notifications into a single message:\n\n"
        f"{numbered}"
    )

    try:
        result = await _synthesizer_agent.run(prompt)
        return result.output
    except Exception as e:
        logger.error(f"Synthesis failed, falling back to concatenation: {e}")
        return "\n\n".join(contents)
