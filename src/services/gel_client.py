"""
Gel Client for FastAPI integration
Follows the recommended pattern from Gel documentation
"""
from gel import create_async_client
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Global client variable
_gel_client = None

async def get_gel_client():
    """
    Get the Gel async client instance.
    Creates a new client if one doesn't exist.
    """
    import logging
    logger = logging.getLogger(__name__)

    logger.info("Getting Gel client instance")
    global _gel_client
    if _gel_client is None:
        logger.info("Creating new Gel client")
        # DIAGNOSTIC: Log the type - create_async_client() returns the client directly
        _gel_client = create_async_client()
        logger.debug(f"create_async_client() returned type: {type(_gel_client)}")
        logger.info(f"Gel client created, type: {type(_gel_client)}")
    else:
        logger.info("Using existing Gel client")
        logger.debug(f"Existing client type: {type(_gel_client)}")
    return _gel_client

@asynccontextmanager
async def get_gel_transaction() -> AsyncGenerator:
    """
    Async context manager for Gel transactions.
    Yields a transaction that will be automatically committed or rolled back.
    """
    import logging
    logger = logging.getLogger(__name__)

    logger.debug("Getting Gel client for transaction")
    client = await get_gel_client()
    logger.debug(f"Got Gel client, type: {type(client)}")
    
    # DIAGNOSTIC: Log transaction creation
    logger.debug("Creating transaction...")
    transaction = client.transaction()
    logger.debug(f"Transaction created, type: {type(transaction)}")
    
    # Use the transaction as an async context manager - this is the correct pattern
    async with transaction:
        logger.debug("Entered transaction context, yielding transaction")
        yield transaction
        logger.debug("Transaction context completed successfully")

async def close_gel_client():
    """
    Close the Gel client connection.
    Should be called during application shutdown.
    """
    global _gel_client
    if _gel_client is not None:
        _gel_client.aclose()
        _gel_client = None