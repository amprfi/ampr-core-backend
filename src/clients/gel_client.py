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

def create_basic_client() -> gel.AsyncIOClient:
    """
    Creates a basic unauthenticated gel client.
    Used for webhook processing and system operations.
    """
    return gel.create_async_client()

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
            if result is None:
                raise GelClientError("Query returned None")
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
            if result is None:
                raise GelClientError("Query_single returned None")
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
