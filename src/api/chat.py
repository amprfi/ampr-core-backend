"""
Chat API endpoints for Ampr 1 frontend (web and mobile).

All endpoints require Hanko authentication (auto-protected by middleware).
User IDs are injected from the authenticated session — callers cannot
specify arbitrary user IDs.

Chat routing to period-specific chats is handled automatically by
createMessage (AMPRFI-97). The message endpoint just passes the channel
and lets the mutation resolve the correct chat.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import BaseModel

from src.middleware.auth import get_current_user_id
from src.middleware.logging import debug_detail
from src.clients.convex_client import get_client
from src.api.responses import generate_ai_response, ResponseContext
from src.models.chat_message import ChatMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ============================================================================
# HELPERS
# ============================================================================

def _current_period() -> str:
    """Return the current period string in YYYY-MM format."""
    now = datetime.now(timezone.utc)
    return f"{now.year}-{now.month:02d}"


def _resolve_chat_id(convex_client, user_id: str, channel: str) -> Optional[str]:
    """
    Look up the current monthly chat for (user, channel).

    Returns the chat ID or None if no chat exists yet.
    """
    period = _current_period()
    chat = convex_client.query("chats:getChatByOwnerChannelPeriod", {
        "owner": user_id,
        "channel": channel,
        "period": period,
    })
    return chat["_id"] if chat else None


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class SendMessageRequest(BaseModel):
    """Request body for sending a chat message."""
    channel: str   # "web" or "app"
    content: str


class SendMessageResponse(BaseModel):
    """Response for a chat message."""
    messages: Optional[list[ChatMessage]] = None  # AI response messages with attribution (web only)
    acknowledged: bool = True


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/message", response_model=SendMessageResponse)
async def send_message(
    payload: SendMessageRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Send a message via the Ampr 1 frontend.

    - channel: "web" → full server-side agent pipeline, returns AI response
    - channel: "app" → stores the message only, returns acknowledgment
    """
    if payload.channel not in ("web", "app"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel: {payload.channel}. Must be 'web' or 'app'.",
        )

    if not payload.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content cannot be empty.",
        )

    convex_client = get_client()

    if payload.channel == "web":
        # Full server-side agent pipeline — same as Telegram flow
        response_context = ResponseContext(
            message_content=payload.content,
            chat_id=None,
            channel="web",
            user_id=user_id,
            convex_client=convex_client,
        )

        try:
            response_messages = await generate_ai_response(response_context)
            # Convert to ChatMessage format for API response
            # For web channel, response_messages are GeneratedResponseMessage objects
            # For other channels, they are strings
            from src.models.chat_message import GeneratedResponseMessage
            
            chat_messages = []
            for msg in response_messages:
                if isinstance(msg, GeneratedResponseMessage):
                    chat_messages.append(ChatMessage(
                        content=msg.content,
                        specialist_module=msg.specialist_module
                    ))
                else:
                    # Backward compatibility for string messages
                    chat_messages.append(ChatMessage(content=msg))
            
            return SendMessageResponse(messages=chat_messages)
        except Exception as e:
            logger.error(f"Error generating AI response for web chat: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=debug_detail(e),
            )

    else:
        # Mobile — store only, no server-side agent
        try:
            created = convex_client.mutation("messages:createMessage", {
                "userId": user_id,
                "role": "user",
                "channel": "app",
                "content": payload.content,
            })
            logger.info(f"Stored app message for user {user_id} in chat {created.get('chat')}")
            return SendMessageResponse(acknowledged=True)
        except Exception as e:
            logger.error(f"Error storing app message: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=debug_detail(e),
            )


@router.get("/history")
async def get_history(
    channel: str = Query(..., description="Channel to get history for (web or app)"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Get message history for the current monthly chat.

    Returns messages for the current (user, channel, period) chat.
    If no chat exists yet, returns an empty list.
    """
    if channel not in ("web", "app"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel: {channel}. Must be 'web' or 'app'.",
        )

    convex_client = get_client()
    chat_id = _resolve_chat_id(convex_client, user_id, channel)

    if not chat_id:
        return {"messages": [], "channel": channel}

    # Fetch the full chat data (messages + summaries) and return messages only
    chat_data = convex_client.query("chats:getChat", {
        "userId": user_id,
        "chatId": chat_id,
    })

    return {
        "messages": chat_data.get("recent_messages", []),
        "channel": channel,
    }


@router.get("/summaries")
async def get_summaries(
    channel: str = Query(..., description="Channel to get summaries for (web or app)"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Get summaries for the current monthly chat.

    Returns summaries for the current (user, channel, period) chat.
    If no chat exists yet, returns an empty list.
    """
    if channel not in ("web", "app"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel: {channel}. Must be 'web' or 'app'.",
        )

    convex_client = get_client()
    chat_id = _resolve_chat_id(convex_client, user_id, channel)

    if not chat_id:
        return {"summaries": [], "channel": channel}

    chat_data = convex_client.query("chats:getChat", {
        "userId": user_id,
        "chatId": chat_id,
    })

    return {
        "summaries": chat_data.get("summaries", []),
        "channel": channel,
    }
