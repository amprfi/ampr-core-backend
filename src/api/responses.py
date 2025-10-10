"""
Shared response handler for AI responses to both SMS and chat messages.

This module provides a unified interface for generating AI responses and handling
the storage and delivery of those responses across different channels (SMS, chat).
"""

import logging
import uuid
from typing import Optional, Dict, Any
from gel import AsyncIOClient
import json

from ..agents.amprChat import get_amprChat_agent, TalkerContext
from ..clients.vonage_client import VonageClient
from ..queries.messaging.create_message_async_edgeql import create_message as create_message_query
from ..queries.messaging.get_chat_async_edgeql import get_chat

# Set up logging
logger = logging.getLogger(__name__)

class ResponseContext:
    """
    Context object for generating AI responses.

    Attributes:
        message_content: The content of the user's message
        chat_id: The ID of the chat
        channel: The channel (sms or chat)
        user_id: The ID of the user
        gel_client: Authenticated Gel client
        phone_number: Optional phone number for SMS responses
    """
    def __init__(
        self,
        message_content: str,
        chat_id: uuid.UUID,
        channel: str,
        user_id: uuid.UUID,
        gel_client: AsyncIOClient,
        phone_number: Optional[str] = None
    ):
        self.message_content = message_content
        self.chat_id = chat_id
        self.channel = channel
        self.user_id = user_id
        self.gel_client = gel_client
        self.phone_number = phone_number

async def generate_ai_response(context: ResponseContext) -> str:
    """
    Generate an AI response and handle storage and delivery.

    Args:
        context: ResponseContext object containing all necessary information

    Returns:
        The AI response content as a string

    Raises:
        Exception: If any step in the process fails
    """
    try:
        logger.info(f"Generating AI response for {context.channel} message in chat {context.chat_id}")

        # Get the talker agent
        amprChat_agent = get_amprChat_agent()

        # Create the context for the agent
        talker_context = TalkerContext(
            gel_client=context.gel_client,
        )

        # Fetch unarchived messages for the current chat to provide context
        chat_data = await get_chat(
            executor=context.gel_client,
            user_id=context.user_id,
            chat_id=context.chat_id
        )

        # Prepare message history context, excluding archived messages
        message_history = []
        for message in chat_data.recent_messages:
            if not message.is_archived:
                message_history.append({
                    "role": message.role,
                    "content": message.content,
                    "timestamp": message.created_at.isoformat() if message.created_at else None
                })

        # Convert to JSON string for context
        message_history_str = json.dumps(message_history)

        # Create a context string that includes both the message history and the current message
        context_str = f"""
        Previous conversation history (most recent first):
        {message_history_str}

        Current message to respond to:
        {context.message_content}
        """

        # Get the agent response with enhanced context
        result = await amprChat_agent.run(
            context_str,
            deps=talker_context,
        )

        # Extract the output string from the AgentRunResult
        response_content = result.output
        logger.info(f"Generated AI response: {response_content}")

        # Store the assistant's response in the database
        await create_message_query(
            executor=context.gel_client,
            user_id=context.user_id,
            role="assistant",
            channel=context.channel,
            content=response_content
        )

        logger.info(f"Stored AI response in database for chat {context.chat_id}")

        # For SMS responses, send the message via Vonage
        if context.channel == "sms" and context.phone_number:
            vonage_client = VonageClient()
            sms_result = vonage_client.send_sms(
                to=context.phone_number,
                text=response_content
            )

            if sms_result:
                logger.info(f"Successfully sent SMS response to {context.phone_number}")
            else:
                logger.error(f"Failed to send SMS response to {context.phone_number}")

        return response_content

    except Exception as e:
        logger.error(f"Error generating AI response: {str(e)}", exc_info=True)
        raise
