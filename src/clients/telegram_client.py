"""
Telegram client module for sending messages via Telegram Bot API.

Provides a simple async client for sending text messages using aiogram.
"""
import logging
from typing import Optional, List, Dict, Any
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from src.config.telegram_config import get_telegram_bot
from src.utils.formatting import markdown_to_telegram_html

logger = logging.getLogger(__name__)


class TelegramClient:
    """
    A client for sending messages via Telegram Bot API.
    
    This client provides methods for sending text messages to Telegram users.
    """
    
    def __init__(self):
        """Initialize the Telegram client."""
        self.bot: Bot = get_telegram_bot()
    
    async def send_message(
        self, 
        chat_id: int, 
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> Optional[dict]:
        """
        Send a text message to a Telegram chat.
        
        Args:
            chat_id: The Telegram chat ID (user ID) to send to
            text: The message text
            reply_markup: Optional inline keyboard markup
            
        Returns:
            Dictionary containing the response data or None if failed
        """
        try:
            text = markdown_to_telegram_html(text)
            message = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup
            )
            logger.info(f"Telegram message sent successfully to chat_id {chat_id}")
            return message.model_dump(exclude_unset=True)
            
        except TelegramAPIError as e:
            logger.error(f"Telegram API error sending to {chat_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Failed to send Telegram message to {chat_id}: {str(e)}")
            return None
    
    def create_inline_keyboard(self, buttons: List[List[Dict[str, str]]]) -> InlineKeyboardMarkup:
        """
        Create an inline keyboard markup.
        
        Args:
            buttons: List of button rows, where each row is a list of button dicts
                    Each button dict should have 'text' and 'callback_data' keys
                    
        Returns:
            InlineKeyboardMarkup object
            
        Example:
            keyboard = client.create_inline_keyboard([
                [{"text": "Option 1", "callback_data": "opt1"}],
                [{"text": "Option 2", "callback_data": "opt2"}]
            ])
        """
        keyboard_rows = []
        for row in buttons:
            keyboard_row = []
            for button in row:
                keyboard_row.append(
                    InlineKeyboardButton(
                        text=button["text"],
                        callback_data=button["callback_data"]
                    )
                )
            keyboard_rows.append(keyboard_row)
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    async def close(self):
        """Close the bot session."""
        await self.bot.session.close()
