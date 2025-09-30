import os
import gel
from fastapi import Request, HTTPException, status
from dotenv import load_dotenv

load_dotenv()

class GelClientError(Exception):
    """Base exception for gel client operations"""
    pass

class AuthenticationError(GelClientError):
    """Raised when authentication fails"""
    pass

class ConstraintViolationError(GelClientError):
    """Raised when database constraints are violated"""
    def __init__(self, message: str):
        super().__init__(message)
        self.status_code = status.HTTP_400_BAD_REQUEST

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

def create_authenticated_client(auth_token: str) -> gel.AsyncIOClient:
    """
    Creates an authenticated gel client with the provided auth token.

    Args:
        auth_token: The authentication token to use for client configuration

    Returns:
        A configured gel.AsyncIOClient with authentication

    Raises:
        AuthenticationError: If the authentication token is invalid or configuration fails
    """
    if not auth_token:
        raise AuthenticationError("Authentication required. Please log in first.")

    gel_client = gel.create_async_client()

    try:
        gel_client = gel_client.with_globals({"ext::auth::client_token": auth_token})
    except Exception as e:
        raise AuthenticationError(f"Invalid authentication token: {str(e)}")

    return gel_client