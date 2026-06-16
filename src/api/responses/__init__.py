"""
Response handlers for AI responses across different channels.

This package provides a unified interface for generating AI responses and handling
the storage and delivery of those responses across different channels (web, Telegram, REST).

The package is structured as:
- context.py: ResponseContext class and related dataclasses
- preprocessing.py: Shared preprocessing logic (date detection, message storage, etc.)
- postprocessing.py: Shared post-processing and delivery helpers
- web.py: Web channel handler
- telegram.py: Telegram channel handler

Main entry points:
- generate_ai_response: Main function that routes to the appropriate channel handler
- ResponseContext: Context object for generating AI responses
"""

from typing import Sequence

from .context import ResponseContext
from .web import generate_web_response as _generate_web_response
from .telegram import generate_telegram_response as _generate_telegram_response


async def generate_ai_response(context: ResponseContext) -> Sequence[str]:
    """
    Generate an AI response and handle storage and delivery.

    This is the main entry point that routes to the appropriate channel-specific handler.
    It preserves the existing behavior by delegating to web or telegram handlers based
    on the channel specified in the context.

    Args:
        context: ResponseContext object containing all necessary information

    Returns:
        list[str]: The generated AI response messages

    Raises:
        Exception: If any step in the process fails
    """
    if context.channel == "telegram":
        return await _generate_telegram_response(context)
    elif context.channel == "web":
        return await _generate_web_response(context)
    elif context.channel == "rest":
        # REST channel uses the same flow as web
        return await _generate_web_response(context)
    else:
        # For other channels (app, execution), use web flow as default
        return await _generate_web_response(context)


__all__ = ["generate_ai_response", "ResponseContext"]
