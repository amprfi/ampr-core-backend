from fastapi import APIRouter, Depends, HTTPException, Request, Query
from gel import AsyncIOClient
import gel
import json
import os
import logging

from src.clients.gel_client import create_basic_client
from src.queries.messaging.get_chat_by_phone_async_edgeql import get_chat_by_phone
from src.queries.messaging.get_user_by_phone_async_edgeql import get_user_by_phone

# Set up logging
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/debug", tags=["debug"])

# Note: We create a fresh client for each request instead of reusing one
# to avoid potential state issues

GEL_AUTH_BASE_URL = os.getenv("GEL_AUTH_BASE_URL")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000/api")


@router.get("/test-get-chat-by-phone")
async def test_get_chat_by_phone(
    phone_number: str = Query(..., description="Phone number to test", alias="phone"),
    request: Request = None
):
    """
    Test endpoint for manually testing the get_chat_by_phone function.

    Args:
        phone_number: The phone number to look up

    Returns:
        dict: Information about the chat found or error message
    """

    # Log all query parameters for debugging
    logger.info(f"All query params: {dict(request.query_params)}")
    logger.info(f"Phone number from query: {phone_number}")

    try:
        # Create a fresh client for each request to avoid state issues
        gel_client = create_basic_client()

        logger.info(f"Testing get_chat_by_phone with phone: {phone_number}")
        logger.info(f"Phone number type: {type(phone_number)}")
        logger.info(f"Client type: {type(gel_client)}")
        logger.info(f"Client globals: {gel_client._globals if hasattr(gel_client, '_globals') else 'No globals'}")

        # Call the function directly with the raw phone number
        chat_results = await get_chat_by_phone(
            executor=gel_client,
            phone_number=phone_number
        )

        if chat_results and len(chat_results) > 0:
            return {
                "status": "success",
                "phone_number": phone_number,
                "chat_id": str(chat_results[0].id),
                "message": f"Found chat with ID: {chat_results[0].id}"
            }
        else:
            return {
                "status": "not_found",
                "phone_number": phone_number,
                "message": f"No chat found for phone number: {phone_number}"
            }

    except Exception as e:
        logger.error(f"Error testing get_chat_by_phone: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "phone_number": phone_number,
            "error": str(e),
            "message": f"Error testing get_chat_by_phone: {str(e)}"
        }

@router.get("/test-get-user-by-phone")
async def test_get_user_by_phone(
    phone_number: str = Query(..., description="Phone number to test", alias="phone"),
    request: Request = None
):
    """
    Test endpoint for manually testing the get_user_by_phone function.

    Args:
        phone_number: The phone number to look up

    Returns:
        dict: Information about the user found or error message
    """

    # Log all query parameters for debugging
    logger.info(f"All query params: {dict(request.query_params)}")
    logger.info(f"Phone number from query: {phone_number}")

    try:
        # Create a fresh client for each request to avoid state issues
        gel_client = create_basic_client()

        # Add detailed logging about the client state
        logger.info(f"Testing get_user_by_phone with phone: {phone_number}")
        logger.info(f"Phone number type: {type(phone_number)}")
        logger.info(f"Client type: {type(gel_client)}")
        logger.info(f"Client globals: {gel_client._globals if hasattr(gel_client, '_globals') else 'No globals'}")

        # Add logging for the query function itself
        logger.info("About to execute get_user_by_phone query")

        # Call the function directly with the raw phone number
        user_result = await get_user_by_phone(
            executor=gel_client,
            phone_number=phone_number
        )

        logger.info(f"Query completed. Result type: {type(user_result)}")
        logger.info(f"Result value: {user_result}")

        if user_result:
            return {
                "status": "success",
                "phone_number": phone_number,
                "user_id": str(user_result.id),
                "message": f"Found user with ID: {user_result.id}"
            }
        else:
            return {
                "status": "not_found",
                "phone_number": phone_number,
                "message": f"No user found for phone number: {phone_number}"
            }

    except Exception as e:
        logger.error(f"Error testing get_user_by_phone: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "phone_number": phone_number,
            "error": str(e),
            "message": f"Error testing get_user_by_phone: {str(e)}"
        }

@router.get("/debug/current-user")
async def get_current_user_debug(request: Request):
    """Debug endpoint to test authentication and return current user info."""
    
    # Step 1: Extract auth token
    auth_token = request.cookies.get("gel-auth-token")
    
    if not auth_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ")[1]
    
    if not auth_token:
        return {
            "error": "No auth token found",
            "cookies": list(request.cookies.keys()),
            "headers": dict(request.headers)
        }
    
    # Step 2: Create authenticated client
    try:
        gel_client = gel.create_async_client()
        authed_client = gel_client.with_globals({"ext::auth::client_token": auth_token})
        
        # Step 3: Test different queries to see what works
        results = {}
        
        # Test 1: Try to get the ClientTokenIdentity directly
        try:
            identity_result = await authed_client.query_single("""
                select global ext::auth::ClientTokenIdentity {
                    id
                }
            """)
            results["client_token_identity"] = identity_result
        except Exception as e:
            results["client_token_identity_error"] = str(e)
        
        # Test 2: Try to find user by identity
        try:
            user_result = await authed_client.query_single("""
                select accessControl::User {
                    id
                }
                filter .identity = global ext::auth::ClientTokenIdentity
            """)
            results["user_by_identity"] = user_result
        except Exception as e:
            results["user_by_identity_error"] = str(e)
        
        # Test 3: List all available globals
        try:
            globals_test = await authed_client.query("""
                select {
                    client_token := global ext::auth::client_token,
                    client_identity := global ext::auth::ClientTokenIdentity,
                }
            """)
            results["globals_test"] = globals_test
        except Exception as e:
            results["globals_test_error"] = str(e)
        
        # Test 4: Check what users exist
        try:
            all_users = await authed_client.query("""
                select accessControl::User {
                    id,
                    identity: {
                        id
                    }
                } 
                limit 5
            """)
            results["sample_users"] = all_users
        except Exception as e:
            results["sample_users_error"] = str(e)
        
        return {
            "auth_token_length": len(auth_token),
            "auth_token_preview": auth_token[:20] + "...",
            "results": results
        }
        
    except Exception as e:
        return {
            "error": f"Client configuration failed: {str(e)}",
            "auth_token_length": len(auth_token),
            "auth_token_preview": auth_token[:20] + "..."
        }
