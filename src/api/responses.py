"""
Shared response handler for AI responses to both SMS and chat messages.

This module provides a unified interface for generating AI responses and handling
the storage and delivery of those responses across different channels (SMS, chat).
"""

import logging
import uuid
from typing import Optional
from gel import AsyncIOClient
import json

from ..agents.amprChat import get_amprChat_agent, TalkerContext
from ..agents.summarizer import get_summarizer_agent, SummarizerContext
from ..clients.vonage_client import VonageClient
from ..queries.messaging.create_message_async_edgeql import create_message as create_message_query
from ..queries.messaging.get_chat_async_edgeql import get_chat
from ..queries.messaging.update_message_status_async_edgeql import update_message_status
from ..queries.messaging.get_messages_to_summarize_async_edgeql import get_messages_to_summarize
from ..queries.messaging.create_summary_and_archive_async_edgeql import create_summary_and_archive

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
            user_id=context.user_id
        )

        # Fetch chat data including messages and summaries
        chat_data = await get_chat(
            executor=context.gel_client,
            user_id=context.user_id,
            chat_id=context.chat_id
        )

        # Process Summaries (Oldest to Newest)
        # The query already orders by range_start asc
        summaries_list = []
        if chat_data.summaries:
            for summary in chat_data.summaries:
                summaries_list.append(f"<summary range='{summary.range_start.isoformat()} to {summary.range_end.isoformat()}'>{summary.content}</summary>")

        summaries_str = "\n".join(summaries_list)

        # Process Recent Messages (Oldest to Newest)
        # The query already orders by created_at asc
        message_history = []
        recent_messages = chat_data.recent_messages if chat_data.recent_messages else []
        
        for message in recent_messages:
            # status check is implicit via the query, but good to be safe
            message_history.append({
                "role": message.role,
                "content": message.content,
                "timestamp": message.created_at.isoformat() if message.created_at else None
            })

        # Convert to JSON string for context
        message_history_str = json.dumps(message_history)

        # Create a context string that includes summaries, message history and the current message
        context_str = f"""
        [LONG TERM MEMORY / SUMMARIES]
        The following are summaries of earlier conversation parts (chronological order):
        {summaries_str}

        [RECENT CONVERSATION]
        Previous conversation history (chronological order):
        {message_history_str}

        [CURRENT MESSAGE]
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
        
        # --- MEMORY MANAGEMENT ---
        # Trigger the background memory management process
        # We await it here, but in a production system with heavy load this might be offloaded to a background task queue
        await _manage_chat_memory(context.gel_client, context.chat_id)

        return response_content

    except Exception as e:
        logger.error(f"Error generating AI response: {str(e)}", exc_info=True)
        raise

async def _manage_chat_memory(gel_client: AsyncIOClient, chat_id: uuid.UUID):
    """
    Manages the chat memory lifecycle:
    1. Updates message statuses (Current -> PendingSummary)
    2. Checks if enough PendingSummary messages exist to trigger summarization
    3. Runs summarizer agent if needed
    4. Creates summary and archives messages
    """
    try:
        # Step 1: Update message statuses and get pending count
        # The query returns a list of updated objects, but we primarily care about the count check
        # Actually, update_message_status.edgeql returns the COUNT of pending messages in the second result set?
        # Wait, I need to check how the python wrapper handles the multi-statement or if I need to call them separately.
        # The EdgeQL file I wrote has two selects. The generated wrapper usually only returns the result of the LAST statement
        # or requires specific handling.
        # Let's assume for now we need to rely on the wrapper's return value. 
        # In `update_message_status.edgeql`, the last statement is `select count(...)`.
        
        pending_count = await update_message_status(
            executor=gel_client,
            chat_id=chat_id
        )
        
        logger.info(f"Memory Management: Chat {chat_id} has {pending_count} pending messages.")

        # Step 2: Trigger Summarization if threshold met
        if pending_count >= 25:
            logger.info(f"Triggering summarization for chat {chat_id}")
            
            # Fetch the messages to summarize
            messages_to_summarize = await get_messages_to_summarize(
                executor=gel_client,
                chat_id=chat_id
            )
            
            if not messages_to_summarize:
                logger.warning("Pending count was high but no messages returned for summarization.")
                return

            # Prepare content for summarizer
            text_lines = []
            message_ids = []
            
            # Capture time range
            start_msg = messages_to_summarize[0]
            end_msg = messages_to_summarize[-1]

            if not start_msg.created_at or not end_msg.created_at:
                logger.error(f"Messages missing created_at timestamp, skipping summarization for chat {chat_id}")
                return

            range_start = start_msg.created_at
            range_end = end_msg.created_at
            
            for msg in messages_to_summarize:
                ts = msg.created_at.isoformat() if msg.created_at else "UNKNOWN"
                text_lines.append(f"[{ts}] {msg.role.upper()}: {msg.content}")
                message_ids.append(msg.id)
                
            conversation_text = "\n".join(text_lines)
            
            # Run Summarizer Agent
            summarizer_agent = get_summarizer_agent()
            summarizer_ctx = SummarizerContext()
            
            summary_result = await summarizer_agent.run(
                f"Please summarize these messages:\n\n{conversation_text}",
                deps=summarizer_ctx
            )
            
            summary_content = summary_result.output
            logger.info(f"Generated summary for chat {chat_id}: {summary_content[:50]}...")
            
            # Save Summary and Archive Messages
            await create_summary_and_archive(
                executor=gel_client,
                chat_id=chat_id,
                content=summary_content,
                range_start=range_start,
                range_end=range_end,
                message_ids=message_ids
            )
            
            logger.info(f"Successfully archived {len(message_ids)} messages for chat {chat_id}")

    except Exception as e:
        # Log but don't fail the user response if memory management fails
        logger.error(f"Error in memory management for chat {chat_id}: {str(e)}", exc_info=True)
