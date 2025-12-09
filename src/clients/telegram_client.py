"""
Telegram client module for sending messages via Telegram Bot API.

Provides a simple async client for sending text messages using aiogram.
"""
import logging
from typing import Optional
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from src.config.telegram_config import get_telegram_bot

logger = logging.getLogger(__name__)


class TelegramClient:
    """
    A client for sending messages via Telegram Bot API.
    
    This client provides methods for sending text messages to Telegram users.
    """
    
    def __init__(self):
        """Initialize the Telegram client."""
        self.bot: Bot = get_telegram_bot()
    
    async def send_message(self, chat_id: int, text: str) -> Optional[dict]:
        """
        Send a text message to a Telegram chat.
        
        Args:
            chat_id: The Telegram chat ID (user ID) to send to
            text: The message text
            
        Returns:
            Dictionary containing the response data or None if failed
        """
        try:
            message = await self.bot.send_message(
                chat_id=chat_id,
                text=text
            )
            logger.info(f"Telegram message sent successfully to chat_id {chat_id}")
            return message.model_dump(exclude_unset=True)
            
        except TelegramAPIError as e:
            logger.error(f"Telegram API error sending to {chat_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Failed to send Telegram message to {chat_id}: {str(e)}")
            return None
    
    async def close(self):
        """Close the bot session."""
        await self.bot.session.close()
