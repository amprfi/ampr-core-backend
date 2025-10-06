"""
Vonage webhook router for handling incoming SMS messages.

This module provides endpoints for receiving and processing Vonage webhooks,
including inbound messages and message status updates.
"""

import os
import logging
import traceback
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel
import json

from ..clients.gel_client import create_basic_client
from ..queries.users.get_user_by_phone_async_edgeql import get_user_by_phone
from ..queries.messaging.get_chat_by_user_async_edgeql import get_chat_by_user
from ..queries.messaging.create_message_async_edgeql import create_message as create_message_query
from ..api.responses import generate_ai_response, ResponseContext

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Security scheme for bearer token
security = HTTPBearer()

class WebhookPayload(BaseModel):
    """Base model for webhook payloads"""
    pass

class InboundMessagePayload(WebhookPayload):
    """
    Model for inbound message webhook payload from Vonage.
    Matches the structure of Vonage Messages API webhooks.
    """
    message_uuid: str
    to: Dict[str, str]
    from_: Dict[str, str]  # 'from' is a reserved word in Python
    timestamp: str
    text: str
    channel: str
    message_type: str
    conversation_id: Optional[str] = None

def get_vonage_api_key() -> str:
    """Get Vonage API key from environment variables"""
    api_key = os.getenv("VONAGE_API_KEY")
    if not api_key:
        raise ValueError("VONAGE_API_KEY environment variable is not set")
    return api_key

def get_vonage_signature_secret() -> str:
    """Get Vonage signature secret from environment variables"""
    secret = os.getenv("VONAGE_SIGNATURE_SECRET")
    if not secret:
        raise ValueError("VONAGE_SIGNATURE_SECRET environment variable is not set")
    return secret

def verify_webhook_signature(token: str, signature_secret: str) -> bool:
    """
    Verify the JWT signature from Vonage webhook.

    Args:
        token: The JWT token from the Authorization header
        signature_secret: The signature secret from environment variables

    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        # Decode the token without verification to get the header
        header = jwt.get_unverified_header(token)

        # Verify the token with the signature secret
        decoded = jwt.decode(
            token,
            signature_secret,
            algorithms=[header.get("alg", "HS256")]
        )

        # Verify the issuer is Vonage
        if decoded.get("iss") != "Vonage":
            logger.error("Invalid issuer in JWT token")
            return False

        return True
    except InvalidTokenError as e:
        logger.error(f"Invalid token: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error verifying token: {str(e)}")
        return False

async def get_webhook_credentials(
    request: Request
) -> HTTPAuthorizationCredentials:
    """
    Dependency to extract and validate webhook credentials.

    Args:
        request: The incoming request

    Returns:
        HTTPAuthorizationCredentials: The authorization credentials

    Raises:
        HTTPException: If authorization fails
    """
    try:
        # Get the signature secret
        signature_secret = get_vonage_signature_secret()

        # Extract the token from the Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header"
            )

        token = auth_header.split(" ")[1]

        # Verify the signature
        if not verify_webhook_signature(token, signature_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )

        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    except Exception as e:
        logger.error(f"Webhook authentication failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}"
        )

def clean_phone_number(phone: str) -> str:
    """
    Clean and normalize a phone number for lookup.

    Args:
        phone: The phone number to clean

    Returns:
        str: Cleaned phone number in format expected by database (digits only with country code)
    """
    # Remove ALL non-digit characters
    cleaned = ''.join(c for c in phone if c.isdigit())

    # Ensure we're returning a string
    if not isinstance(cleaned, str):
        logger.error(f"clean_phone_number returned non-string type: {type(cleaned)}")
        raise ValueError(f"Expected string but got {type(cleaned)}")

    return cleaned

@router.post("/inbound-message", status_code=status.HTTP_200_OK)
async def handle_inbound_message_post(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(get_webhook_credentials)
):
    """
    Handle inbound SMS messages from Vonage using POST with JSON body.

    Args:
        request: The incoming request containing the message data
        credentials: Validated webhook credentials

    Returns:
        dict: Success message

    Raises:
        HTTPException: If no user is found for the phone number
    """
    return await _process_inbound_message(request)

@router.get("/inbound-message", status_code=status.HTTP_200_OK)
async def handle_inbound_message_get(request: Request):
    """
    Handle inbound SMS messages from Vonage using GET with query parameters.

    This endpoint receives SMS messages from Vonage via GET request with query parameters,
    validates the API key, finds the appropriate user for the sender's phone number,
    and stores the message.

    Args:
        request: The incoming request containing query parameters

    Returns:
        dict: Success message

    Raises:
        HTTPException: If authentication fails or no user is found
    """
    # Get query parameters directly from request
    query_params = request.query_params

    # Extract required parameters
    api_key = query_params.get("api-key")
    messageId = query_params.get("messageId")
    to = query_params.get("to")
    text = query_params.get("text")
    msisdn = query_params.get("msisdn")

    # Extract optional parameters
    keyword = query_params.get("keyword")
    type = query_params.get("type")
    message_timestamp = query_params.get("message-timestamp")

    # Validate required parameters
    if not all([api_key, messageId, to, text, msisdn]):
        missing = []
        if not api_key: missing.append("api-key")
        if not messageId: missing.append("messageId")
        if not to: missing.append("to")
        if not text: missing.append("text")
        if not msisdn: missing.append("msisdn")
        logger.error(f"Missing required query parameters: {', '.join(missing)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required parameters: {', '.join(missing)}"
        )

    # Validate API key
    expected_api_key = get_vonage_api_key()
    if api_key != expected_api_key:
        logger.error(f"Invalid API key attempted: {api_key}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    # Create a mock request object with JSON body to reuse existing processing logic
    class MockRequest:
        def __init__(self, data):
            self._json = data

        async def json(self):
            return self._json

    # Convert query params to the expected JSON format
    mock_request_data = {
        "text": text,
        "from": {"number": msisdn},
        "to": {"number": to},
        "message_uuid": messageId,
        "timestamp": message_timestamp,
        "channel": "sms",
        "message_type": type or "text"
    }

    logger.info(f"Received inbound message via GET: {json.dumps(mock_request_data, indent=2)}")

    mock_request = MockRequest(mock_request_data)
    return await _process_inbound_message(mock_request)

async def _process_inbound_message(request):
    """
    Common processing logic for inbound messages (used by both GET and POST endpoints).

    This function:
    1. Extracts the phone number from the message
    2. Uses the phone number to get the user ID
    3. Creates a message in the database using the user ID

    Args:
        request: The request object (real or mock) containing message data

    Returns:
        dict: Success message

    Raises:
        HTTPException: If processing fails (no user found, etc.)
    """
    try:
        # Parse the request data
        data = await request.json()
        logger.info(f"Processing inbound message: {json.dumps(data, indent=2)}")

        # Validate required fields
        if not data.get("text") or not data.get("from") or not data.get("from").get("number"):
            logger.error("Missing required message fields in payload")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required message fields"
            )

        # Create a basic Gel client (no auth needed for system operations)
        gel_client = create_basic_client()

        # Extract and clean phone number
        from_number = data["from"]["number"]
        cleaned_phone = clean_phone_number(from_number)
        logger.info(f"Processing message from phone: {from_number}, cleaned: {cleaned_phone}")

        # Step 1: Get user ID by phone number
        try:
            logger.debug(f"Looking up user by phone: {cleaned_phone}")
            user_result = await get_user_by_phone(
                executor=gel_client,
                phone=cleaned_phone
            )
            user_id = user_result.id
            logger.info(f"Found user with ID: {user_id}")
        except Exception as e:
            logger.error(f"No user found for phone {cleaned_phone}: {e}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Error details: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No user found for phone number {cleaned_phone}"
            )

        # Step 2: Create the message in the database
        message_content = data["text"]
        logger.info(f"Storing message for user {user_id}: {message_content}")

        # The create_message function will automatically find or create a chat for the user
        message_result = await create_message_query(
            executor=gel_client,
            user_id=user_id,  # Use the user ID we found
            role="user",  # Treat as user message
            channel="sms",  # Match the channel in our schema
            content=message_content  # Store just the text content
        )

        logger.info(f"Successfully stored inbound SMS message from {from_number} for user {user_id}")

        # Step 3: Generate AI response
        try:
            # Get the chat ID for this user
            chat_results = await get_chat_by_user(
                executor=gel_client,
                user_id=user_id
            )

            if not chat_results or len(chat_results) == 0:
                logger.error(f"No chat found for phone number {cleaned_phone}")
                raise ValueError(f"No chat found for phone number {cleaned_phone}")

            chat_id = chat_results[0].id

            # Create response context
            response_context = ResponseContext(
                message_content=message_content,
                chat_id=chat_id,
                channel="sms",
                user_id=user_id,
                gel_client=gel_client,
                phone_number=from_number
            )

            # Generate and send AI response
            await generate_ai_response(response_context)
            logger.info(f"Successfully generated and sent AI response for SMS from {from_number}")

        except Exception as e:
            logger.error(f"Error generating AI response for SMS: {str(e)}", exc_info=True)
            # Continue even if response generation fails to ensure message is stored

        return {"status": "success", "message": "Inbound message processed"}

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON payload: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error processing inbound message: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing message: {str(e)}"
        )

@router.post("/message-status", status_code=status.HTTP_200_OK)
async def handle_message_status(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(get_webhook_credentials)
):
    """
    Handle message status updates from Vonage.

    Args:
        request: The incoming request containing status data
        credentials: Validated webhook credentials

    Returns:
        dict: Success message
    """
    try:
        data = await request.json()
        logger.info(f"Received message status: {json.dumps(data, indent=2)}")

        # Here you would typically update the status of a previously sent message
        # For now, we'll just log it
        return {"status": "success", "message": "Message status processed"}

    except Exception as e:
        logger.error(f"Error processing message status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing status: {str(e)}"
        )
