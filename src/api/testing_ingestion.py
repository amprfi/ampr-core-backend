"""
Testing ingestion router for local development and testing.

This module provides the REST testing endpoint for direct message communication
without authentication, intended for local development and testing only.
"""

import logging
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..clients.convex_client import get_client
from ..api.responses import generate_ai_response, ResponseContext
from ..utils.phone import normalize_phone_number

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

    Args:
        payload: Message payload with simplified format

    Returns:
        dict: Response containing success status and AI response

    Raises:
        HTTPException: If processing errors occur
    """
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
    # Create a container to capture the AI response
    ai_response_container: Dict[str, Optional[str]] = {"response": None}

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

        # Generate and capture AI response
        response_messages = await generate_ai_response(response_context)
        ai_response_container["response"] = response_messages
        logger.info(f"Successfully generated AI response for REST message from {from_number}")

    except Exception as e:
        logger.error(f"Error generating AI response for REST message: {str(e)}", exc_info=True)
        # Continue even if response generation fails

    return {
        "status": "success",
        "message": "Inbound message processed",
        "ai_response": ai_response_container["response"]
    }
