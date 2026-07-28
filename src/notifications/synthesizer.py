"""
Notification synthesizer.

Uses an LLM to combine multiple pending notifications from the same module
into a single coherent message for delivery to the user.

Uses the shared Mistral SDK client (see AMPRFI-120 / AMPRFI-126).
"""
import logging

from ..agents.mistral_helpers import (
    get_shared_client,
    build_messages,
    extract_text_from_content,
    MODEL_SMALL,
)

logger = logging.getLogger(__name__)

# Temperature for notification synthesis.  A moderate value keeps the
# output deterministic while still allowing the model some flexibility in
# phrasing and redundancy elimination.
_SYNTHESIS_TEMPERATURE = 0.3

# Reasoning effort is "none" — combining short notification strings does
# not require chain-of-thought reasoning, and "none" returns a plain
# string (rather than a list of reasoning chunks) which simplifies
# extraction.
_SYNTHESIS_REASONING_EFFORT = "none"

_SYSTEM_PROMPT = (
    "You combine multiple notification messages into a single concise, "
    "coherent notification for the user. Preserve all important information "
    "(asset names, prices, percentages, thresholds) but eliminate redundancy. "
    "Use a natural, conversational tone. Do not add greetings or sign-offs. "
    "If the notifications are about different assets, organize by asset. "
    "Keep the combined message as brief as possible while retaining all "
    "key data points."
)


async def synthesize_notifications(contents: list[str]) -> str:
    """
    Combine multiple notification messages into one.

    Args:
        contents: List of individual notification content strings.

    Returns:
        A single synthesized message string.

    Behavior:
        - Single content (fast path): returns the original content unchanged.
        - Multiple contents: uses the shared Mistral SDK client to synthesize
          a combined message, preserving key data points (asset names,
          prices, percentages, thresholds).
        - On any SDK failure (including blank/empty responses): falls back to
          newline-concatenation of the original contents so delivery is never
          blocked by an LLM outage or empty output.
    """
    # Fast path: zero or single notification needs no synthesis
    if len(contents) <= 1:
        return contents[0] if contents else ""

    numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(contents))
    prompt = (
        f"Combine these {len(contents)} notifications into a single message:\n\n"
        f"{numbered}"
    )

    messages = build_messages(_SYSTEM_PROMPT, prompt)

    try:
        client = get_shared_client()
        response = await client.chat.complete_async(
            model=MODEL_SMALL,
            messages=messages,
            temperature=_SYNTHESIS_TEMPERATURE,
            reasoning_effort=_SYNTHESIS_REASONING_EFFORT,
        )

        content = response.choices[0].message.content
        synthesized = extract_text_from_content(content)

        # Treat blank output as a synthesis failure so the caller falls back
        # to newline-concatenation rather than delivering an empty message
        # (which Telegram would reject, causing notification loss).
        if not synthesized.strip():
            raise ValueError("Mistral synthesis returned empty content")

        logger.info(f"Synthesized {len(contents)} notifications into {len(synthesized)} chars")
        return synthesized

    except Exception as e:
        logger.error(f"Synthesis failed, falling back to concatenation: {e}")
        return "\n\n".join(contents)
