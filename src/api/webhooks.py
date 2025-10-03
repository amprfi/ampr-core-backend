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

from src.clients.gel_client import create_basic_client
from src.queries.messaging.get_chat_by_phone_async_edgeql import get_chat_by_phone
from src.queries.messaging.create_message_async_edgeql import create_message as create_message_query

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

    # Phone numbers are stored in DB as simple digit strings with country code
    # Example: "18472840023" (1 = US country code)
    # If the number doesn't start with 1 (US country code), add it
    if not cleaned.startswith('1'):
        cleaned = '1' + cleaned

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
        HTTPException: If no chat is found for the phone number
    """
    return await _process_inbound_message(request)

@router.get("/inbound-message", status_code=status.HTTP_200_OK)
async def handle_inbound_message_get(request: Request):
    """
    Handle inbound SMS messages from Vonage using GET with query parameters.

    This endpoint receives SMS messages from Vonage via GET request with query parameters,
    validates the API key, finds the appropriate chat for the sender's phone number,
    and stores the message.

    Args:
        request: The incoming request containing query parameters

    Returns:
        dict: Success message

    Raises:
        HTTPException: If authentication fails or no chat is found
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

    Args:
        request: The request object (real or mock) containing message data

    Returns:
        dict: Success message

    Raises:
        HTTPException: If processing fails
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

        # Find the chat for this phone number
        try:
            logger.debug(f"DEBUG: Raw phone number from request: {from_number}")
            logger.debug(f"DEBUG: Cleaned phone number: {cleaned_phone}")
            logger.debug(f"DEBUG: Phone number length: {len(cleaned_phone)}")
            logger.debug(f"DEBUG: Phone number type: {type(cleaned_phone)}")
            logger.debug(f"DEBUG: Phone number repr: {repr(cleaned_phone)}")

            # Try to get the chat
            chat_result = await get_chat_by_phone(
                executor=gel_client,
                phone_number=cleaned_phone
            )
            chat_id = chat_result.id
            logger.info(f"Found existing chat: {chat_id}")
        except Exception as e:
            logger.error(f"No chat found for phone {cleaned_phone}: {e}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Error details: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")

            # Try a direct query to see what's in the DB
            try:
                logger.debug("Attempting direct query to check phone numbers in DB...")
                # This is a placeholder - we would need the actual query syntax
                # all_chats = await gel_client.query("SELECT Chat { phone_number }")
                # logger.debug(f"All chats in DB: {all_chats}")
            except Exception as db_e:
                logger.debug(f"Could not query all chats: {db_e}")

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No chat found for phone number {cleaned_phone}"
            )

        # Create the message in the database
        message_content = data["text"]
        logger.info(f"Storing message in chat {chat_id}: {message_content}")

        await create_message_query(
            executor=gel_client,
            user_id=None,  # System message (no specific user)
            chat_id=chat_id,
            role="user",  # Treat as user message
            channel="sms",  # Match the channel in our schema
            content=message_content  # Store just the text content
        )

        logger.info(f"Successfully stored inbound SMS message from {from_number} in chat {chat_id}")
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
