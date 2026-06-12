"""
Webhook router for handling incoming messages from external services.

This module provides endpoints for:
- Telegram webhook updates
- Local REST API endpoint for development/testing

Temporary Local REST Endpoint:
---------------------------------
For local development/testing, a temporary endpoint is available at POST /webhooks/rest-message.

This endpoint:
- Bypasses all authentication (for local use only)
- Accepts a simplified message format:
  {
    "text": "message content",
    "from_number": "sender phone number",
    "to_number": "recipient phone number"
  }
- Returns both a success message and the generated AI response
- Should NOT be used in production

Example response format:
{
  "status": "success",
  "message": "Inbound message processed",
  "ai_response": "The generated AI response text"
}
"""

import logging
import time
import uuid
import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, HTTPException, status
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


class RestMessagePayload(BaseModel):
    """
    Model for temporary local REST API message payload.
    Simplified format for direct local API communication.
    """
    text: str
    from_number: str
    to_number: str


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
    import asyncio
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
        
        # chat_id is resolved by createMessage inside generate_ai_response,
        # which auto-creates a period-specific chat if needed.
        response_context = ResponseContext(
            message_content=message_text,
            chat_id=None,
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
