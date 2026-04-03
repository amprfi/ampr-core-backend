"""
Vonage webhook router for handling incoming SMS messages.

This module provides endpoints for receiving and processing Vonage webhooks,
including inbound messages and message status updates.

Temporary Local REST Endpoint:
---------------------------------
For local development/testing when Vonage is unavailable, a temporary endpoint
is available at POST /webhooks/rest-message.

This endpoint:
- Bypasses all authentication (for local use only)
- Accepts a simplified message format:
  {
    "text": "message content",
    "from_number": "sender phone number",
    "to_number": "recipient phone number"
  }
- Uses the same processing pipeline as Vonage messages but with direct AI response capture
- Returns both a success message and the generated AI response
- Should NOT be used in production

Example response format:
{
  "status": "success",
  "message": "Inbound message processed",
  "ai_response": "The generated AI response text"
}
"""

import asyncio
import os
import logging
import time
import traceback
import uuid
import datetime
from typing import Optional, Dict, Any, Set
from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel
import json
from aiogram.types import Update as TelegramUpdate
from aiogram.types import Message as TelegramMessage
from aiogram.types import Contact, CallbackQuery

from ..clients.convex_client import get_client
from ..api.responses import generate_ai_response, ResponseContext
from ..config.telegram_config import get_telegram_webhook_secret

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Security scheme for bearer token
security = HTTPBearer()

# Telegram update_id deduplication
_seen_update_ids: Dict[int, float] = {}
_SEEN_TTL = 300  # 5 minutes


def _is_duplicate_update(update_id: int) -> bool:
    """Check if we've already processed this update_id, and prune stale entries."""
    now = time.monotonic()
    # Prune entries older than TTL
    stale = [uid for uid, ts in _seen_update_ids.items() if now - ts > _SEEN_TTL]
    for uid in stale:
        del _seen_update_ids[uid]

    if update_id in _seen_update_ids:
        return True
    _seen_update_ids[update_id] = now
    return False

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

class RestMessagePayload(BaseModel):
    """
    Model for temporary local REST API message payload.
    Simplified format for direct local API communication.
    """
    text: str
    from_number: str
    to_number: str

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

def normalize_phone_number(phone: str) -> str:
    """
    Normalize a phone number to consistent storage/lookup format.
    
    Removes all non-digit characters (tel:, +, -, spaces, etc.)
    Returns digits only with country code.

    Args:
        phone: The phone number to normalize

    Returns:
        str: Normalized phone number (digits only)
    """
    # Remove ALL non-digit characters
    normalized = ''.join(c for c in phone if c.isdigit())

    # Ensure we're returning a string
    if not isinstance(normalized, str):
        logger.error(f"normalize_phone_number returned non-string type: {type(normalized)}")
        raise ValueError(f"Expected string but got {type(normalized)}")

    return normalized

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

    # Create a mock request object with the expected JSON format
    class MockRequest:
        def __init__(self, data):
            self._json = data

        async def json(self):
            return self._json

    # Convert payload to the format expected by _process_inbound_message
    mock_request_data = {
        "text": payload.text,
        "from": {"number": payload.from_number},
        "to": {"number": payload.to_number},
        "message_uuid": "rest-" + str(uuid.uuid4()),  # Generate a unique ID
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "channel": "rest",
        "message_type": "text"
    }

    logger.info(f"Received local REST message: {json.dumps(mock_request_data, indent=2)}")

    # Create a container to capture the AI response
    ai_response_container: Dict[str, Optional[str]] = {"response": None}

    # Create a custom processing function that captures the AI response
    async def process_rest_message():
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
        try:
            chat = convex_client.query("chats:getChatByUser", {"userId": user_id})
            if not chat:
                logger.error(f"No chat found for user {user_id}")
                raise ValueError(f"No chat found for user {user_id}")
            chat_id = chat["_id"]

            # Create response context
            response_context = ResponseContext(
                message_content=message_content,
                chat_id=chat_id,
                channel="rest",
                user_id=user_id,
                convex_client=convex_client,
                phone_number=from_number
            )

            # Generate and capture AI response
            response_messages = await generate_ai_response(response_context)
            ai_response_container["response"] = response_messages
            logger.info(f"Successfully generated AI response for REST message from {from_number}")

        except Exception as e:
            logger.error(f"Error generating AI response for REST message: {str(e)}", exc_info=True)
            # Continue even if response generation fails

        return {"status": "success", "message": "Inbound message processed"}

    # Process the message and capture any exceptions
    try:
        await process_rest_message()
        return {
            "status": "success",
            "message": "Inbound message processed",
            "ai_response": ai_response_container["response"]
        }
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error processing REST message: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing message: {str(e)}"
        )

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

        # Get the global Convex client
        convex_client = get_client()

        # Extract and normalize phone number
        from_number = data["from"]["number"]
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
        message_content = data["text"]
        channel = data.get("channel", "sms")
        logger.info(f"Processing message for user {user_id}: {message_content}")

        # Step 3: Generate AI response (which will also store the user message)
        try:
            chat = convex_client.query("chats:getChatByUser", {"userId": user_id})
            if not chat:
                logger.error(f"No chat found for user {user_id}")
                raise ValueError(f"No chat found for user {user_id}")
            chat_id = chat["_id"]

            # Create response context
            response_context = ResponseContext(
                message_content=message_content,
                chat_id=chat_id,
                channel=channel,
                user_id=user_id,
                convex_client=convex_client,
                phone_number=from_number
            )

            # Generate and send AI response
            await generate_ai_response(response_context)
            logger.info(f"Successfully generated and sent AI response from {from_number}")

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

def verify_telegram_secret(request: Request) -> bool:
    """
    Verify the secret token from Telegram webhook request.
    
    Args:
        request: The incoming request
        
    Returns:
        bool: True if secret is valid
    """
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    expected_secret = get_telegram_webhook_secret()
    return secret_header == expected_secret


@router.post("/telegram", status_code=status.HTTP_200_OK)
async def handle_telegram_webhook(request: Request):
    """
    Handle incoming updates from Telegram via webhook.
    
    Returns 200 immediately to prevent Telegram retries, then processes
    the message in a background task. Deduplicates by update_id.
    
    Args:
        request: The incoming webhook request from Telegram
        
    Returns:
        dict: Success response (returned immediately)
    """
    logger.info("Received Telegram webhook update")
    
    # Verify secret token
    if not verify_telegram_secret(request):
        logger.error("Invalid Telegram webhook secret")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid secret token"
        )
    
    # Parse update eagerly so we can deduplicate before spawning background work
    data = await request.json()
    logger.info(f"Telegram update data: {data}")
    update = TelegramUpdate.model_validate(data)

    # Deduplicate retries from Telegram
    if _is_duplicate_update(update.update_id):
        logger.info(f"Skipping duplicate Telegram update_id {update.update_id}")
        return {"status": "ok"}

    # Return 200 immediately; process in background
    asyncio.create_task(_process_telegram_update(update))
    return {"status": "ok"}


async def _process_telegram_update(update: TelegramUpdate):
    """Background processing of a Telegram update."""
    telegram_id = None
    try:
        # Get Convex client
        convex_client = get_client()
        
        # Handle callback queries (inline keyboard button clicks)
        if update.callback_query:
            logger.info(f"Callback query detected: {update.callback_query}")
            await _handle_callback_query(update.callback_query, convex_client)
            return
        
        # Only handle text messages for now
        if not update.message:
            logger.info(f"Ignoring non-message update. Update type: message={update.message}, callback_query={update.callback_query}")
            return
        
        message: TelegramMessage = update.message
        
        # Ensure from_user exists
        if not message.from_user:
            logger.error("Message missing from_user information")
            return
        
        telegram_id = str(message.from_user.id)
        message_text = message.text or ""
        
        logger.info(f"Processing Telegram message from user {telegram_id}: {message_text}")
        logger.info(f"Message has contact: {message.contact is not None}, has text: {message.text is not None}")
        
        # Check if user shared contact (for linking) - handle BEFORE text check
        if message.contact:
            logger.info(f"Contact detected! Processing contact sharing for user {telegram_id}")
            await _handle_contact_sharing(convex_client, message.contact, telegram_id)
            return
        
        # Ensure message has text
        if not message.text:
            logger.info("Ignoring non-text, non-contact message")
            return
        
        # Look up user by Telegram ID
        user = convex_client.query("users:getUserByTelegramId", {"telegram_id": telegram_id})
        
        if not user:
            # Check if user typed a phone number or email (for linking)
            if message_text and (message_text.replace('+', '').replace('-', '').replace(' ', '').isdigit() or '@' in message_text):
                logger.info(f"User {telegram_id} provided contact info for linking: {message_text}")
                
                # Try to find existing user by phone or email
                existing_user = None
                if '@' in message_text:
                    # Email
                    try:
                        existing_user = convex_client.query("users:getUserByEmail", {"email": message_text})
                    except Exception as e:
                        logger.info(f"No user found with email {message_text}")
                else:
                    # Phone number
                    normalized_phone = normalize_phone_number(message_text)
                    try:
                        existing_user = convex_client.query("users:getUserByPhone", {"phone": normalized_phone})
                    except Exception as e:
                        logger.info(f"No user found with phone {normalized_phone}")
                
                if existing_user:
                    # Link telegram_id to existing user
                    convex_client.mutation("users:updateUser", {
                        "id": existing_user["_id"],
                        "telegram_id": telegram_id
                    })
                    
                    from ..clients.telegram_client import TelegramClient
                    telegram_client = TelegramClient()
                    await telegram_client.send_message(
                        chat_id=int(telegram_id),
                        text="✅ Your account has been linked! You can now chat with me."
                    )
                    await telegram_client.close()
                    return
                else:
                    from ..clients.telegram_client import TelegramClient
                    telegram_client = TelegramClient()
                    await telegram_client.send_message(
                        chat_id=int(telegram_id),
                        text=f"❌ No existing account found with {message_text}. Please try again or select 'I'm new to Ampr' to create a new account."
                    )
                    await telegram_client.close()
                    await _show_user_options(telegram_id)
                    return
            
            # Show inline keyboard with options
            logger.info(f"Telegram user {telegram_id} not found, showing options")
            await _show_user_options(telegram_id)
            return
        
        user_id = user["_id"]
        logger.info(f"Found linked user: {user_id}")
        
        # Get chat (will be auto-created by createMessage if it doesn't exist)
        chat = convex_client.query("chats:getChatByUser", {"userId": user_id})
        chat_id = chat["_id"] if chat else None
        
        # Generate AI response (handles both onboarding and regular chat)
        response_context = ResponseContext(
            message_content=message_text,
            chat_id=chat_id,
            channel="telegram",
            user_id=user_id,
            convex_client=convex_client,
            telegram_id=telegram_id
        )
        
        await generate_ai_response(response_context)
        logger.info(f"Successfully processed Telegram message from {telegram_id}")
        
    except Exception as e:
        logger.error(f"Error processing Telegram webhook: {str(e)}", exc_info=True)
        # Send a friendly error message to the user
        try:
            if telegram_id:
                from ..clients.telegram_client import TelegramClient
                telegram_client = TelegramClient()
                await telegram_client.send_message(
                    chat_id=int(telegram_id),
                    text="⚠️ Something went wrong processing your message. Please try again in a moment."
                )
                await telegram_client.close()
        except Exception as notify_err:
            logger.error(f"Failed to send error notification to user: {notify_err}")


async def _handle_contact_sharing(convex_client, contact: Contact, telegram_id: str):
    """
    Handle when user shares their phone number contact.
    Links the Telegram ID to the user account.
    """
    phone_number = contact.phone_number
    normalized_phone = normalize_phone_number(phone_number)
    
    logger.info(f"User {telegram_id} shared contact - raw phone: {phone_number}, normalized: {normalized_phone}")
    
    try:
        # Link Telegram ID to user
        result = convex_client.mutation("users:linkTelegramToUser", {
            "phone": normalized_phone,
            "telegram_id": telegram_id
        })
        logger.info(f"Successfully linked Telegram ID {telegram_id} to phone {normalized_phone}, user_id: {result}")
        
        # Send confirmation
        from ..clients.telegram_client import TelegramClient
        telegram_client = TelegramClient()
        await telegram_client.send_message(
            chat_id=int(telegram_id),
            text="✅ Your account has been linked! You can now chat with me."
        )
        await telegram_client.close()
        
    except Exception as e:
        logger.error(f"Error linking Telegram account - phone: {normalized_phone}, error: {str(e)}", exc_info=True)
        # Send error message to user
        from ..clients.telegram_client import TelegramClient
        telegram_client = TelegramClient()
        await telegram_client.send_message(
            chat_id=int(telegram_id),
            text=f"❌ Could not link your account. Please make sure your phone number {normalized_phone} is registered."
        )
        await telegram_client.close()
        raise


async def _show_user_options(telegram_id: str):
    """
    Show inline keyboard with options for new/existing users.
    """
    from ..clients.telegram_client import TelegramClient
    
    telegram_client = TelegramClient()
    
    keyboard = telegram_client.create_inline_keyboard([
        [{"text": "🆕 I'm new to Ampersand", "callback_data": "new_user"}],
        [{"text": "🔗 Link my existing account", "callback_data": "link_account"}]
    ])
    
    logger.info(f"Created inline keyboard: {keyboard.model_dump() if hasattr(keyboard, 'model_dump') else keyboard}")
    
    result = await telegram_client.send_message(
        chat_id=int(telegram_id),
        text="👋 Welcome to Ampersand (alpha), the world's first open financial operating system. I'm Ampr, your financial co-pilot. How would you like to get started?",
        reply_markup=keyboard
    )
    
    logger.info(f"Send message result: {result}")
    
    await telegram_client.close()
    logger.info(f"Sent user options to Telegram user {telegram_id}")


async def _handle_callback_query(callback_query: CallbackQuery, convex_client):
    """
    Handle inline keyboard button clicks.
    """
    from ..clients.telegram_client import TelegramClient
    
    telegram_id = str(callback_query.from_user.id)
    callback_data = callback_query.data
    
    logger.info(f"Handling callback query from {telegram_id}: {callback_data}")
    
    telegram_client = TelegramClient()
    
    try:
        # Answer the callback query to remove loading state
        await telegram_client.bot.answer_callback_query(callback_query.id)
        
        if callback_data == "new_user":
            # Check if user already exists with this telegram_id
            existing_user = convex_client.query("users:getUserByTelegramId", {"telegram_id": telegram_id})
            
            if existing_user:
                user = existing_user
                user_id = user["_id"]
                logger.info(f"Found existing user with Telegram ID {telegram_id}: {user_id}")
            else:
                # Create new user with just telegram_id
                logger.info(f"Creating new user with Telegram ID {telegram_id}")
                user = convex_client.mutation("users:createUser", {
                    "telegram_id": telegram_id
                })
                user_id = user["_id"]
                logger.info(f"Created new user: {user_id}")
            
            # Use generate_ai_response which will detect onboarding is needed
            response_context = ResponseContext(
                message_content="I'm a new user to Ampr. Help me get started.",
                chat_id=None,
                channel="telegram",
                user_id=user_id,
                convex_client=convex_client,
                telegram_id=telegram_id
            )
            await generate_ai_response(response_context)
            
        elif callback_data == "link_account":
            # For linking, we'll prompt them to provide contact info
            # Then search for existing user and link telegram_id
            await telegram_client.send_message(
                chat_id=int(telegram_id),
                text="To link your existing account, please provide your phone number or email."
            )
        
        await telegram_client.close()
        return {"status": "ok", "message": "Callback handled"}
        
    except Exception as e:
        logger.error(f"Error handling callback query: {str(e)}", exc_info=True)
        await telegram_client.send_message(
            chat_id=int(telegram_id),
            text="❌ Something went wrong. Please try again."
        )
        await telegram_client.close()
        return {"status": "error", "message": str(e)}
