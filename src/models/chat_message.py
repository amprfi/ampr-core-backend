"""
Chat message models for AI response generation.

This module provides data structures for attributed chat messages
used in multi-module response flows.
"""

from typing import Optional
from pydantic import BaseModel


class ChatMessage(BaseModel):
    """
    A chat message with optional module attribution.
    
    Used in API responses to return messages with information about
    which specialist module (if any) generated the response.
    
    Attributes:
        content: The message content
        specialist_module: Optional name of the specialist module that generated this message
    """
    content: str
    specialist_module: Optional[str] = None


class GeneratedResponseMessage:
    """
    Internal response object for multi-module response generation.
    
    Keeps generated text and attribution coupled during the response
    generation pipeline. Used internally before converting to API response format.
    
    Attributes:
        content: The generated response content
        specialist_module: The name of the specialist module that generated this, or None
    """
    def __init__(self, content: str, specialist_module: Optional[str] = None):
        self.content = content
        self.specialist_module = specialist_module
    
    def to_chat_message(self) -> ChatMessage:
        """Convert to API ChatMessage format."""
        return ChatMessage(
            content=self.content,
            specialist_module=self.specialist_module
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary format."""
        result = {"content": self.content}
        if self.specialist_module:
            result["specialist_module"] = self.specialist_module
        return result
