import os
import gel
from fastapi import Request, HTTPException, status
from dotenv import load_dotenv

load_dotenv

class GelClientError(Exception):
    """Base exception for gel client operations"""
    pass

class AuthenticationError(GelClientError):
    """Raised when authentication fails"""
    pass

class ConstraintViolationError(GelClientError):
    """Raised when database constraints are violated"""
    def __init__(self, message: str):
        super().__init__(message, status.HTTP_400_BAD_REQUEST)

def create_basic_client() -> gel.AsyncIOClient:
    """
    Creates a basic unauthenticated gel client.
    Used for public operations and initial auth flows.
    """
    return gel.create_async_client()