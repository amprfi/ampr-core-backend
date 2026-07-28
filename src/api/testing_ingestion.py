"""
Testing ingestion router for local development and testing.

This module provides the REST testing endpoint for direct message communication
without authentication, intended for local development and testing only.

Manual Testing Instructions
===========================

Prerequisites:
    - The application must be running in a local/development environment,
      or ENABLE_REST_TESTING_ENDPOINT=true must be set.
    - The Convex backend must be accessible and have at least one user
      with a phone number matching the `from_number` in the request.

Request:
    POST /api/webhooks/rest-message
    Content-Type: application/json

    {
        "text": "What is the price of Bitcoin?",
        "from_number": "+15551234567",
        "to_number": "+15550000000"
    }

Expected Response (200 OK):
    {
        "status": "success",
        "message": "Inbound message processed",
        "ai_response": [
            {
                "content": "Bitcoin is currently trading at $100,000...",
                "specialist_module": "defianalyst"
            },
            {
                "content": "Based on market analysis...",
                "specialist_module": null
            }
        ]
    }

Error Responses:
    - 404: Endpoint disabled (production without opt-in) or user not found
    - 502: AI response generation failed
"""

import logging
from typing import Optional, Dict, List, Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..clients.convex_client import get_client
from ..api.responses import generate_ai_response, ResponseContext
from ..config.environment import is_rest_testing_endpoint_enabled
from ..utils.phone import normalize_phone_number
from ..models.chat_message import GeneratedResponseMessage

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["testing"])


class RestMessagePayload(BaseModel):
    """
    Model for temporary local REST API message payload.
    Simplified format for direct local API communication.
    """
    text: str
    from_number: str
    to_number: str


@router.post("/rest-message", status_code=status.HTTP_200_OK)
async def handle_rest_message(
    payload: RestMessagePayload
):
    """
    Temporary local REST API endpoint for direct message communication.
    Bypasses all authentication for local development/testing.

    This endpoint is gated to local/development environments only.
    In production, it returns 404 unless ENABLE_REST_TESTING_ENDPOINT=true.

    Args:
        payload: Message payload with simplified format

    Returns:
        dict: Response containing success status and AI response with
              stable shape: {"content": str, "specialist_module": Optional[str]}

    Raises:
        HTTPException: 404 if endpoint is disabled or user not found,
                       502 if AI response generation fails
    """
    # Environment gate: disable in production unless explicitly opted in
    if not is_rest_testing_endpoint_enabled():
        logger.warning(
            "REST testing endpoint accessed in a non-development environment "
            "without opt-in. Returning 404."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not available"
        )

    logger.warning("Using temporary local REST endpoint - no authentication")

    # Get the global Convex client
    convex_client = get_client()

    # Extract and normalize phone number
    from_number = payload.from_number
    normalized_phone = normalize_phone_number(from_number)
    logger.info(f"Processing message from phone: {from_number}, normalized: {normalized_phone}")

    # Step 1: Get user ID by phone number
    try:
        logger.debug(f"Looking up user by phone: {normalized_phone}")
        user = convex_client.query("users:getUserByPhone", {"phone": normalized_phone})
        if not user:
            raise ValueError(f"No user found for phone {normalized_phone}")
        user_id = user["_id"]
        logger.info(f"Found user with ID: {user_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"No user found for phone {normalized_phone}: {e}")
        logger.error(f"Error type: {type(e)}")
        logger.error(f"Error details: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user found for phone number {normalized_phone}"
        )

    # Step 2: Get message content
    message_content = payload.text
    logger.info(f"Processing message for user {user_id}: {message_content}")

    # Step 3: Generate AI response (which will also store the user message)
    try:
        # chat_id is resolved by createMessage inside generate_ai_response,
        # which auto-creates a period-specific chat if needed.
        response_context = ResponseContext(
            message_content=message_content,
            chat_id=None,
            channel="rest",
            user_id=user_id,
            convex_client=convex_client,
        )

        # Generate AI response
        response_messages = await generate_ai_response(response_context)
        logger.info(f"Successfully generated AI response for REST message from {from_number}")

    except Exception as e:
        logger.error(f"Error generating AI response for REST message: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI response generation failed"
        )

    # Convert response messages to JSON-serializable dicts with a stable shape.
    # Each entry has "content" (str) and "specialist_module" (Optional[str]).
    # GeneratedResponseMessage objects carry attribution; plain strings are
    # wrapped with specialist_module=None for backward compatibility.
    ai_response: List[Dict[str, Any]] = []
    for msg in response_messages:
        if isinstance(msg, GeneratedResponseMessage):
            ai_response.append({
                "content": msg.content,
                "specialist_module": msg.specialist_module,
            })
        else:
            # Fallback for plain string responses
            ai_response.append({
                "content": str(msg),
                "specialist_module": None,
            })

    return {
        "status": "success",
        "message": "Inbound message processed",
        "ai_response": ai_response
    }
