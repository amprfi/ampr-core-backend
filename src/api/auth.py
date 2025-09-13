import os
import secrets
import hashlib
import base64
import httpx
import logging
from fastapi import APIRouter, Response, Request, HTTPException, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
GEL_AUTH_BASE_URL = os.getenv("GEL_AUTH_BASE_URL")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL")

# Debug logging to check environment variables
logger.info(f"GEL_AUTH_BASE_URL: {repr(GEL_AUTH_BASE_URL)}")
logger.info(f"SERVER_BASE_URL: {repr(SERVER_BASE_URL)}")

class MagicLinkRequest(BaseModel):
    email: EmailStr

def generate_pkce():
    verifier = secrets.token_urlsafe(32)
    challenge = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(challenge).decode('utf-8').rstrip('=')

@router.post("/auth/magic-link/send")
async def request_magic_link(request_data: MagicLinkRequest, response: Response):
    verifier, challenge = generate_pkce()
    response.set_cookie(
        key="gel-pkce-verifier", value=verifier,
        httponly=True, secure=True, samesite='strict', max_age=900
    )
    email_url = f"{GEL_AUTH_BASE_URL}/magic-link/email"
    callback_url = f"{SERVER_BASE_URL}/auth/magic-link/callback"

    # Debug logging for URL construction
    logger.info(f"Constructed email_url: {repr(email_url)}")
    logger.info(f"Constructed callback_url: {repr(callback_url)}")

    async with httpx.AsyncClient() as client:
        # Log the request details
        logger.info(f"Sending magic link request to: {email_url}")
        payload = {
            "challenge": f"{challenge[:10]}...",
            "email": request_data.email,
            "provider": "builtin::local_magic_link",
            "callback_url": callback_url,
            "redirect_on_failure": callback_url
        }
        logger.info(f"Request payload: {payload}")

        magic_link_response = await client.post(
            email_url,
            json={
                "challenge": challenge,
                "email": request_data.email,
                "provider": "builtin::local_magic_link",  # Match your GelDB provider name
                "callback_url": callback_url,
                "redirect_on_failure": callback_url,  # Required by GelDB auth service
                "create_missing": True,  # Create email factor if it doesn't exist
            }
        )

        # Log the response details
        logger.info(f"Response status: {magic_link_response.status_code}")
        logger.info(f"Response content: {magic_link_response.text}")
    if magic_link_response.status_code == 200:
        return {"message": "Magic link sent. Check your email!"}
    elif magic_link_response.status_code == 404:
        # user doesn't exist; could handle registration if desired
        return {"message": "User not found."}
    else:
        raise HTTPException(status_code=400, detail=magic_link_response.text)

@router.get("/auth/magic-link/callback")
async def magic_link_callback(
    request: Request,
    code: str = None,
    error: str = None,
    gel_pkce_verifier: str = Cookie(None)
):
    if error:
        raise HTTPException(status_code=400, detail=f"Magic link error: {error}")
    if not code or not gel_pkce_verifier:
        raise HTTPException(status_code=400, detail="Missing info for magic link auth.")

    token_url = f"{GEL_AUTH_BASE_URL}/token"
    async with httpx.AsyncClient() as client:
        token_response = await client.get(token_url, params={"code": code, "verifier": gel_pkce_verifier})
    if token_response.status_code != 200:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    token_data = token_response.json()
    auth_token = token_data.get("auth_token")

    response = JSONResponse(content={"message": "Authenticated!"})
    response.set_cookie("gel-auth-token", auth_token, httponly=True, secure=True, samesite='strict')
    response.delete_cookie("gel-pkce-verifier")
    return response

@router.post("/auth/logout")
async def logout():
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("gel-auth-token")
    return response
