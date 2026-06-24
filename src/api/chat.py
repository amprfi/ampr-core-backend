"""
Chat API endpoints for Ampr 1 frontend (web and mobile).

All endpoints require Hanko authentication (auto-protected by middleware).
User IDs are injected from the authenticated session — callers cannot
specify arbitrary user IDs.

Chat routing to period-specific chats is handled automatically by
createMessage (AMPRFI-97). The message endpoint just passes the channel
and lets the mutation resolve the correct chat.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.middleware.auth import get_current_user_id
from src.middleware.logging import debug_detail
from src.clients.convex_client import get_client
from src.api.responses import generate_ai_response, ResponseContext
from src.api.responses.streaming import generate_streaming_response
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


# ============================================================================
# STREAMING ENDPOINT (AMPRFI-114)
# ============================================================================

@router.post("/stream", response_class=StreamingResponse)
async def stream_message(
    payload: SendMessageRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Stream a chat message response using AI SDK UI Message Stream protocol.
    
    This endpoint provides token-level streaming for web chat, compatible with
    Vercel AI SDK UI (@ai-sdk/vue). It emits SSE (Server-Sent Events) with the
    AI SDK UI Message Stream data protocol.
    
    **Authentication:** Same Hanko user-facing auth as `/api/chat/message`
    
    **Request Body:** Same shape as `/api/chat/message`:
    ```json
    {
        "channel": "web",
        "content": "..."
    }
    ```
    
    **Response:**
    - Content-Type: text/event-stream
    - Header: x-vercel-ai-ui-message-stream: v1
    - Body: SSE stream with AI SDK UI Message Stream parts
    
    **Stream Parts:**
    - Standard: start, text-start, text-delta, text-end, finish
    - Custom (Ampersand): data-module-start, data-module-text, data-module-end,
      data-module-error, data-status, data-unresolved-triggers, data-turn-metadata,
      data-turn-complete
    
    **Behavior:**
    - Zero-module: streams general amprChat text deltas
    - Single-module: streams module's synthesized response with attribution
    - Multi-module: runs module synthesis concurrently, interleaves faster modules
    - All-or-nothing persistence: assistant messages persisted only after aggregate
      turn completes successfully; partial output NOT persisted on failure
    - Never exposes Mistral reasoning/thinking chunks to client
    - Runs same preprocessing flow as non-streaming (date, currency, watchlist, etc.)
    
    **Frontend Integration:**
    The frontend should use AI SDK UI transport request transformation to map
    the latest UI message to {channel, content}. The backend accepts the same
    request shape as `/api/chat/message`.
    
    **Note:** Currently supports `channel="web"` only. Other channels will return 400.
    """
    if payload.channel != "web":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel for streaming: {payload.channel}. Only 'web' is supported.",
        )

    if not payload.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content cannot be empty.",
        )

    convex_client = get_client()
    
    # Create response context for streaming
    response_context = ResponseContext(
        message_content=payload.content,
        chat_id=None,
        channel="web",
        user_id=user_id,
        convex_client=convex_client,
    )

    # Generate streaming response
    async def generate_sse():
        try:
            async for sse_data in generate_streaming_response(response_context):
                yield sse_data
        except Exception as e:
            logger.error(f"Error in streaming response: {e}", exc_info=True)
            # Emit error part before re-raising so frontend gets error signal
            error_data = {"type": "error", "errorText": str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"
            # Emit [DONE] terminator for clean stream termination
            yield "data: [DONE]\n\n"
            raise

    # Return streaming response with required headers
    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
        },
    )
