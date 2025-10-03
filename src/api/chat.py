import os
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from pydantic_ai import Agent
from gel import AsyncIOClient
import gel
import uuid
import json

from src.clients.gel_client import create_authenticated_client, create_authenticated_client_with_user, AuthenticationError
from src.agents.amprChat import get_amprChat_agent, TalkerContext
from src.common.types import CommonChat, CommonMessage
from src.queries.users.get_current_user_id_async_edgeql import get_current_user_id
from src.queries.messaging.create_chat_async_edgeql import create_chat as create_chat_query

from dotenv import load_dotenv
load_dotenv()

router = APIRouter()
client = gel.create_async_client()

GEL_AUTH_BASE_URL = os.getenv("GEL_AUTH_BASE_URL")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000/api")

async def get_authenticated_client_with_user(request: Request) -> AsyncIOClient:
    """Get a fully configured client with both auth token and current_user global set."""

    # Extract auth token from cookies or headers
    auth_token = request.cookies.get("gel-auth-token")
    if not auth_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ")[1]
        elif not auth_token:
            auth_token = request.headers.get("X-Gel-Auth-Token")

    if not auth_token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in first."
        )

    # Get the current user ID
    basic_client = create_authenticated_client(auth_token)
    try:
        user_result = await get_current_user_id(executor=basic_client)
        if not user_result or not user_result.id:
            raise HTTPException(
                status_code=401,
                detail="Could not determine current user"
            )

        # Create a client with both auth token and user context
        return create_authenticated_client_with_user(auth_token, user_result.id)

    except Exception as e:
        print(f"Error configuring client: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Invalid authentication token: {str(e)}"
        )

class MessageRequest(BaseModel):
    chat_id: uuid.UUID | None = None
    message: CommonMessage

@router.get("/chat/{chat_id}")
async def get_chat(
    chat_id: uuid.UUID,
    gel_client: AsyncIOClient = Depends(get_authenticated_client_with_user)
) -> CommonChat:
    """Get chat by ID - simplified to just return basic chat info for now"""
    from src.queries.messaging.get_chat_async_edgeql import get_chat as get_chat_query

    # Get user_id from the authenticated client
    user_result = await get_current_user_id(executor=gel_client)
    if user_result is None:
        raise HTTPException(status_code=401, detail="User authentication failed")
    user_id = user_result.id

    result = await get_chat_query(
        executor=gel_client,
        user_id=user_id,
        chat_id=chat_id
    )

    return CommonChat.from_gel_result(result)

@router.post("/chat/message")
async def send_message(
    message_request: MessageRequest,
    gel_client: AsyncIOClient = Depends(get_authenticated_client_with_user)
):
    """Send a message to a chat and return the response"""
    from src.queries.messaging.create_message_async_edgeql import create_message as create_message_query

    # Get user_id from the authenticated client
    user_result = await get_current_user_id(executor=gel_client)
    if user_result is None:
        raise HTTPException(status_code=401, detail="User authentication failed")
    user_id = user_result.id

    # Store the user message first
    # Use message channel if available, otherwise default to "chat"
    channel = message_request.message.channel or "chat"
    await create_message_query(
        executor=gel_client,
        user_id=user_id,
        role=message_request.message.role,
        channel=channel,
        content=message_request.message.content
    )

    # Get the talker agent
    amprChat_agent = get_amprChat_agent()

    # Create the context (simplified without memory components)
    context = TalkerContext(
        gel_client=gel_client,
    )

    # Get the agent response
    result = await amprChat_agent.run(
        message_request.message.content or "",
        deps=context,
    )

    # Extract the output string from the AgentRunResult
    response_content = result.output

    # Store the assistant's response
    await gel_client.query(
        """
        insert messaging::Message {
            chat := (select assert_exists((select messaging::Chat filter .id = <uuid>$chat_id))),
            role := 'assistant',
            content := <str>$content,
            created_at := datetime_current(),
            channel := <str>$channel,
            is_archived := false,
        }
        """,
        chat_id=message_request.chat_id,
        content=response_content,
        channel="chat",  # Use same channel as user message
    )

    return {"response": response_content}

@router.post("/chat")
async def create_chat(
    gel_client: AsyncIOClient = Depends(get_authenticated_client_with_user)
) -> CommonChat:
    """Create a new chat"""

    try:
        # The client already has both auth token and user context set
        # Get the user_id from the client's current_user global
        user_result = await get_current_user_id(executor=gel_client)
        if user_result is None:
            raise HTTPException(status_code=401, detail="User authentication failed")

        user_id = user_result.id
        print(f"DEBUG: Using user_id: {user_id}")

        # This should work since the global is already set
        result = await create_chat_query(executor=gel_client, user_id=user_id)
        print(f"DEBUG: create_chat_query result: {result}")

        return CommonChat.from_gel_result(result)

    except Exception as e:
        print(f"DEBUG: Exception in create_chat: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create chat: {str(e)}"
        )