from fastapi import APIRouter, Depends, HTTPException, Request
from gel import AsyncIOClient
import gel
import json
import os


router = APIRouter()
client = gel.create_async_client()

GEL_AUTH_BASE_URL = os.getenv("GEL_AUTH_BASE_URL")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000/api")


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
