import os
import logging
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

def create_authenticated_client_with_user(auth_token: str, user_id: str) -> gel.AsyncIOClient:
    """
    Creates an authenticated gel client with both auth token and user context.

    Args:
        auth_token: The authentication token to use for client configuration
        user_id: The user ID to set as the current user in the client

    Returns:
        A configured gel.AsyncIOClient with both authentication and user context

    Raises:
        AuthenticationError: If the authentication token is invalid or configuration fails
    """
    if not auth_token:
        raise AuthenticationError("Authentication required. Please log in first.")

    if not user_id:
        raise AuthenticationError("User ID is required for user context.")

    gel_client = gel.create_async_client()

    try:
        gel_client = gel_client.with_globals({
            "ext::auth::client_token": auth_token,
            "accessControl::current_user": user_id
        })
    except Exception as e:
        raise AuthenticationError(f"Failed to configure client: {str(e)}")

    return gel_client

# Configure logging
logger = logging.getLogger(__name__)

# Enable detailed logging if DEBUG environment variable is set
if os.getenv('DEBUG', 'False').lower() == 'true':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logging.getLogger('gel').setLevel(logging.DEBUG)
    logger.info("GelDB query logging enabled")

    # Monkey patch gel client to add query logging
    original_query = gel.AsyncIOClient.query
    original_query_single = gel.AsyncIOClient.query_single

    async def logged_query(self, query, *args, **kwargs):
        logger.debug(f"Executing query: {query}")
        logger.debug(f"Query args: {args}, kwargs: {kwargs}")
        try:
            result = await original_query(self, query, *args, **kwargs)
            logger.debug(f"Query result: {result}")
            return result
        except Exception as e:
            logger.error(f"Query error: {str(e)}")
            raise

    async def logged_query_single(self, query, *args, **kwargs):
        logger.debug(f"Executing query_single: {query}")
        logger.debug(f"Query args: {args}, kwargs: {kwargs}")
        try:
            result = await original_query_single(self, query, *args, **kwargs)
            logger.debug(f"Query_single result: {result}")
            return result
        except Exception as e:
            logger.error(f"Query_single error: {str(e)}")
            raise

    gel.AsyncIOClient.query = logged_query
    gel.AsyncIOClient.query_single = logged_query_single

    # Add logging for client creation
    original_create_async_client = gel.create_async_client

    def logged_create_async_client(*args, **kwargs):
        logger.debug(f"Creating new gel client with args: {args}, kwargs: {kwargs}")
        try:
            client = original_create_async_client(*args, **kwargs)
            logger.debug(f"Client created successfully")
            return client
        except Exception as e:
            logger.error(f"Client creation error: {str(e)}", exc_info=True)
            raise

    gel.create_async_client = logged_create_async_client