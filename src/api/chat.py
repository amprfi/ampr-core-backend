import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai import Agent
from gel import AsyncIOClient
import gel
import uuid
import json

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

    gel_client = gel.create_async_client()

    try:
        # Set the auth token - this should be enough for basic authentication
        gel_client = gel_client.with_globals({"ext::auth::client_token": auth_token})
        print("Successfully configured client with auth token")

        # Get the current user
        user_result = await get_current_user_id(executor=gel_client)
        if user_result and user_result.id:
            # Create a new client with both auth token and current_user
            gel_client = gel.create_async_client().with_globals({
                "accessControl::current_user": user_result.id,
                "ext::auth::client_token": auth_token
            })
            print(f"Successfully configured client with current_user: {user_result.id}")
        else:
            raise HTTPException(
                status_code=401,
                detail="Could not determine current user"
            )
    except Exception as e:
        print(f"Error configuring client: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Invalid authentication token: {str(e)}"
        )

    return gel_client

class MessageRequest(BaseModel):
    chat_id: uuid.UUID
    message: CommonMessage

@router.get("/chat/{chat_id}")
async def get_chat(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    gel_client: AsyncIOClient = Depends(lambda: client)
) -> CommonChat:
    """Get chat by ID - simplified to just return basic chat info for now"""
    from src.queries.messaging.get_chat_async_edgeql import get_chat as get_chat_query

    result = await get_chat_query(
        executor=gel_client,
        user_id=user_id,
        chat_id=chat_id
    )

    return CommonChat.from_gel_result(result)

@router.post("/chat/{chat_id}/message")
async def send_message(
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    message_request: MessageRequest,
    gel_client: AsyncIOClient = Depends(lambda: client)
):
    """Send a message to a chat and stream the response"""
    from src.queries.messaging.create_message_async_edgeql import create_message as create_message_query

    # Store the user message first
    await create_message_query(
        executor=gel_client,
        user_id=user_id,
        chat_id=chat_id,
        role=message_request.message.role,
        content=message_request.message.content
    )

    async def generate_response():
        # Send thinking status
        yield f"data: {json.dumps({'type': 'status', 'message': '*thinking...*'})}\n\n"
        
        # Get the talker agent
        amprChat_agent = get_amprChat_agent()
        
        # Create the context (simplified without memory components)
        context = TalkerContext(
            gel_client=gel_client,
        )
        
        # Stream the agent response
        full_response = ""
        async with amprChat_agent.run_stream(
            message_request.message.content or "",
            deps=context,
        ) as result:
            async for text in result.stream_text():
                full_response += text
                yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
        
        # Store the assistant's response
        await gel_client.query(
            """
            insert Message {
                chat := (select assert_exists((select Chat filter .id = $chat_id))),
                llm_role := 'assistant',
                body := $content,
                created_at := datetime_current(),
                is_evicted := false,
            }
            """,
            chat_id=chat_id,
            content=full_response,
        )
        
        # Send completion signal
        yield f"data: {json.dumps({'type': 'complete'})}\n\n"

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
        },
    )

@router.post("/chat")
async def create_chat(
    request: Request,
    gel_client: AsyncIOClient = Depends(get_authenticated_client_with_user)
) -> CommonChat:
    """Create a new chat"""
    
    # The client already has accessControl::current_user set, so we just need 
    # to get the user_id that was used to set it
    try:
        user_result = await get_current_user_id(executor=gel_client)
        if user_result is None:
            raise HTTPException(status_code=401, detail="User authentication failed")
        
        user_id = user_result.id
        print(f"DEBUG: Using user_id: {user_id}")

        current_global = await gel_client.query_single("select global accessControl::current_user")
        print(f"DEBUG: Current global user: {current_global}")
        
        # This should now work since the global is already set
        result = await create_chat_query(executor=gel_client, user_id=user_id)
        print(f"DEBUG: create_chat_query result: {result}")
        
        return CommonChat.from_gel_result(result)
        
    except Exception as e:
        print(f"DEBUG: Exception in create_chat: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create chat: {str(e)}"
        )