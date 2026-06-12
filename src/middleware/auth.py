"""
Hanko Authentication Middleware for Ampersand

Provides:
- Global middleware for automatic protection of /api/* endpoints
- FastAPI dependency for granular auth control
- Session validation via Hanko's /sessions/validate endpoint
- Lazy user creation: creates Convex user on first authenticated request

Token Extraction:
- Session tokens are accepted via the 'hanko' cookie (web browsers)
  or the Authorization: Bearer header (mobile / native clients)
- Per Hanko docs: "Protected API requests must include the session token
  either in a Cookie header or as a Bearer token in the Authorization header."

Security Model:
- All /api/* endpoints are protected by default (safety net)
- Public endpoints must be explicitly excluded
- Dependencies can add additional checks (e.g., admin role)
- Users are automatically synced to Convex on first request
"""

import os
import logging
from typing import Optional, Tuple
from fastapi import Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_500_INTERNAL_SERVER_ERROR, HTTP_503_SERVICE_UNAVAILABLE
import httpx

logger = logging.getLogger(__name__)


async def validate_hanko_session(session_token: str) -> Tuple[str, Optional[str]]:
    """
    Validate a Hanko session token with the Hanko API.
    
    Args:
        session_token: The Hanko session JWT (from 'hanko' cookie or Authorization: Bearer header)
        
    Returns:
        Tuple of (hanko_user_id, email) if valid
        
    Raises:
        HTTPException: If the session is invalid or validation fails
    """
    HANKO_API_URL = os.environ.get("HANKO_API_URL", "")
    if not HANKO_API_URL:
        logger.error("HANKO_API_URL environment variable not set")
        raise HTTPException(
            status_code=500,
            detail="Authentication service not configured"
        )
    
    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="No session token provided"
        )
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{HANKO_API_URL}/sessions/validate",
                json={"session_token": session_token},
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                logger.warning(
                    f"Hanko session validation failed with status {response.status_code}"
                )
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired session"
                )
            
            data = response.json()
            
            if not data.get("is_valid", False):
                logger.warning("Hanko session token is not valid")
                raise HTTPException(
                    status_code=401,
                    detail="Invalid session token"
                )
            
            # Extract user ID from claims (preferred) or fallback to user_id
            claims = data.get("claims", {})
            hanko_user_id = claims.get("subject") or data.get("user_id")
            
            if not hanko_user_id:
                logger.error("No user ID found in Hanko session validation response")
                raise HTTPException(
                    status_code=401,
                    detail="No user ID in session"
                )
            
            # Extract email from claims if available
            email = None
            email_claim = claims.get("email")
            if email_claim and isinstance(email_claim, dict):
                email = email_claim.get("address")
            
            return hanko_user_id, email
            
    except httpx.TimeoutException:
        logger.error("Hanko session validation timeout")
        raise HTTPException(
            status_code=503,
            detail="Authentication service timeout"
        )
    except httpx.RequestError as e:
        logger.error(f"Hanko session validation error: {e}")
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable"
        )
    except Exception as e:
        logger.error(f"Unexpected error validating Hanko session: {e}")
        raise HTTPException(
            status_code=500,
            detail="Authentication error"
        )


async def require_admin_key(request: Request) -> None:
    """
    Dependency for /api/admin/* endpoints.
    Requires a valid X-Admin-Key header matching the ADMIN_API_KEY env var.
    """
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    if not admin_key:
        raise HTTPException(
            status_code=503,
            detail="Admin access not configured"
        )
    if request.headers.get("X-Admin-Key") != admin_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid admin key"
        )


async def get_current_user_id(request: Request) -> str:
    """
    Dependency that returns the authenticated user's Convex ID.

    Use this on user-scoped endpoints so the caller doesn't supply
    their own user_id — they get whatever the auth layer resolved.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )
    return user_id


async def require_hanko_auth(request: Request) -> str:
    """
    FastAPI dependency that requires a valid Hanko session.

    Use this for endpoints that need explicit auth documentation
    or additional authorization checks.

    Args:
        request: FastAPI Request object

    Returns:
        The Hanko user ID

    Raises:
        HTTPException: If not authenticated
    """
    # Check if middleware already set the user ID (preferred path)
    if hasattr(request.state, "hanko_user_id"):
        return request.state.hanko_user_id

    # Fallback: try to validate directly (for endpoints not behind middleware)
    token = _extract_session_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )

    hanko_user_id, _ = await validate_hanko_session(token)
    return hanko_user_id


def _extract_session_token(request: Request) -> Optional[str]:
    """
    Extract the Hanko session token from the request.

    Checks the 'hanko' cookie first (web browsers), then falls back to
    the Authorization: Bearer header (mobile / API clients).

    Per Hanko docs: "Protected API requests must include the session token
    either in a Cookie header or as a Bearer token in the Authorization header."

    Args:
        request: FastAPI Request object

    Returns:
        The session token string, or None if not found
    """
    # Prefer cookie (set automatically by Hanko Elements / Frontend SDK)
    cookie = request.cookies.get("hanko")
    if cookie:
        return cookie

    # Fall back to Authorization: Bearer header (mobile / native clients)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):].strip()
        if token:
            return token

    return None


class HankoAuthMiddleware(BaseHTTPMiddleware):
    """
    Global middleware that protects all /api/* endpoints by default.
    
    This provides a safety net: new endpoints are automatically protected
    unless explicitly excluded.
    
    Lazy User Creation:
    On the first authenticated request, if the user doesn't exist in Convex,
    a new user record is automatically created with the Hanko user ID.
    This eliminates the need for webhooks (Pro/Enterprise feature).
    
    Excluded paths (public endpoints):
    - /api/auth/webhook (Hanko webhook receiver - kept for future use)
    - / (root endpoint)
    - /health (health check)
    - /docs (API documentation)
    - /openapi.json (OpenAPI schema)
    """
    
    # Exact paths that should not require authentication
    EXCLUDED_PATHS = {
        "/",
        "/health",
        "/docs",
        "/openapi.json",
    }

    # Path prefixes that bypass Hanko auth
    # - /api/admin/* — authenticated via X-Admin-Key dependency instead
    # - /api/webhooks/* — external callbacks (Telegram, etc.)
    EXCLUDED_PREFIXES = (
        "/api/admin/",
        "/api/webhooks/",
    )

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip authentication for excluded paths
        if path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Skip authentication for excluded prefixes
        if any(path.startswith(prefix) for prefix in self.EXCLUDED_PREFIXES):
            return await call_next(request)

        # Only apply to API paths
        if not path.startswith("/api/"):
            return await call_next(request)
        
        # Extract Hanko session token (cookie or Bearer header)
        session_token = _extract_session_token(request)

        if not session_token:
            logger.warning(
                f"Unauthenticated request to {request.url.path} - "
                "no hanko cookie or Authorization header"
            )
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication required"}
            )

        # Validate the session and get Hanko user ID
        hanko_user_id: str
        email: Optional[str] = None
        try:
            hanko_user_id, email = await validate_hanko_session(session_token)
        except HTTPException as e:
            # Convert HTTPException to proper response
            return JSONResponse(
                status_code=e.status_code,
                content={"detail": e.detail}
            )
        except Exception as e:
            logger.error(f"Error during Hanko auth middleware: {e}")
            return JSONResponse(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Authentication error"}
            )
        
        # Lazy user creation: check if user exists in Convex, create if not
        try:
            from src.clients.convex_client import get_client
            client = get_client()
            
            # Try to find existing user by hankoId
            convex_user = client.query("users:getUserByHankoId", {"hankoId": hanko_user_id})
            
            if not convex_user:
                # User doesn't exist in Convex - create them
                logger.info(f"Creating Convex user for Hanko user {hanko_user_id}")
                user_id = client.mutation("users:createOrUpdateUserFromHanko", {
                    "hankoId": hanko_user_id,
                    "email": email,
                })
                convex_user_id = user_id
                # Re-fetch to get full user data
                convex_user = client.query("users:getUserByHankoId", {"hankoId": hanko_user_id})
            else:
                convex_user_id = convex_user["_id"]
            
            # Store user info in request state
            request.state.user_id = convex_user_id
            request.state.hanko_user_id = hanko_user_id
            request.state.user_email = email
            if convex_user:
                request.state.user = convex_user
                
        except Exception as e:
            logger.error(f"Error during lazy user creation: {e}")
            return JSONResponse(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "User synchronization error"}
            )
        
        # Proceed to the route handler
        return await call_next(request)
