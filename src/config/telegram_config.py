"""
Telegram bot configuration module.

Provides functions to load Telegram credentials from environment variables
and create configured Bot instance.
"""

import os
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties


def get_telegram_bot_token() -> str:
    """
    Get the Telegram bot token from environment variables.
    
    Returns:
        str: The bot token
        
    Raises:
        ValueError: If TELEGRAM_BOT_TOKEN is not set
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")
    return token


def get_telegram_webhook_secret() -> str:
    """
    Get the webhook secret for validating Telegram requests.
    
    Returns:
        str: The webhook secret
        
    Raises:
        ValueError: If TELEGRAM_WEBHOOK_SECRET is not set
    """
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not secret:
        raise ValueError("TELEGRAM_WEBHOOK_SECRET environment variable is not set")
    return secret


def get_telegram_webhook_path() -> str:
    """
    Get the webhook path for Telegram updates.
    
    Returns:
        str: The webhook path (default: /api/webhooks/telegram)
    """
    return os.getenv("TELEGRAM_WEBHOOK_PATH", "/api/webhooks/telegram")


def get_telegram_bot() -> Bot:
    """
    Create and return a configured Telegram Bot instance.
    
    Returns:
        Bot: Configured aiogram Bot instance
        
    Raises:
        ValueError: If required environment variables are missing
    """
    token = get_telegram_bot_token()
    
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode="HTML")
    )
