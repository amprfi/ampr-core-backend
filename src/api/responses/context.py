"""
Response context and dataclasses for AI response generation.

This module provides the core context objects and data structures used
throughout the response generation pipeline.
"""

import logging
from typing import Optional
from convex import ConvexClient

from ...clients.async_convex_client import AsyncConvexClient, get_async_client

logger = logging.getLogger(__name__)


class ResponseContext:
    """
    Context object for generating AI responses.

    Contains all the information needed to generate and deliver an AI response,
    including message content, chat metadata, user information, and database clients.

    Attributes:
        message_content: The content of the user's message
        chat_id: The ID of the chat (optional, will be auto-created if None)
        channel: The channel (telegram, app, web, rest, execution)
        user_id: The ID of the user
        convex_client: Sync Convex client (legacy, used by agents that still need it)
        async_convex_client: Async Convex client for non-blocking DB calls
        telegram_id: Optional Telegram chat ID for Telegram responses
    """
    def __init__(
        self,
        message_content: str,
        chat_id: Optional[str],
        channel: str,
        user_id: str,
        convex_client: ConvexClient,
        telegram_id: Optional[str] = None
    ):
        self.message_content = message_content
        self.chat_id = chat_id
        self.channel = channel
        self.user_id = user_id
        self.convex_client = convex_client
        self.async_convex_client = get_async_client()
        self.telegram_id = telegram_id
