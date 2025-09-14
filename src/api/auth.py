import os
import secrets
import hashlib
import base64
import httpx
import gel
from fastapi import APIRouter, Response, Request, HTTPException, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from dotenv import load_dotenv
load_dotenv()

router = APIRouter()
client = gel.create_async_client()

GEL_AUTH_BASE_URL = os.getenv("GEL_AUTH_BASE_URL")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:5001")

class MagicLinkRequest(BaseModel):
    email: EmailStr

def generate_pkce():
    verifier = secrets.token_urlsafe(32)
    challenge = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(challenge).decode('utf-8').rstrip('=')

@router.post("/auth/magic-link/send")
async def request_magic_link(request_data: MagicLinkRequest, response: Response):
    """Request a magic link for EXISTING users (sign-in)."""
    verifier, challenge = generate_pkce()
    response.set_cookie(
        key="gel-pkce-verifier", value=verifier,
        httponly=True, secure=True, samesite='strict', max_age=900
    )
    
    email_url = f"{GEL_AUTH_BASE_URL}/magic-link/email"
    callback_url = f"{SERVER_BASE_URL}/auth/magic-link/callback"

    async with httpx.AsyncClient() as http_client:
        magic_link_response = await http_client.post(
            email_url,
            json={
                "challenge": challenge,
                "email": request_data.email,
                "provider": "builtin::local_magic_link",
                "callback_url": callback_url,
            }
        )
    
    if magic_link_response.status_code == 200:
        return {"message": "Magic link sent! Check your email."}
    else:
        # User doesn't exist - they need to sign up
        raise HTTPException(
            status_code=404, 
            detail="User not found. Please sign up first."
        )

@router.post("/auth/magic-link/signup")
async def signup_magic_link(request_data: MagicLinkRequest, response: Response):
    """Register a NEW user with magic link."""
    verifier, challenge = generate_pkce()
    response.set_cookie(
        key="gel-pkce-verifier", value=verifier,
        httponly=True, secure=True, samesite='strict', max_age=900
    )
    
    register_url = f"{GEL_AUTH_BASE_URL}/magic-link/register"
    callback_url = f"{SERVER_BASE_URL}/auth/magic-link/callback"
    callback_url += "?isSignUp=true"  # Signal this is a signup
    
    async with httpx.AsyncClient() as http_client:
        # Log the request details for debugging
        request_data_log = {
            "challenge": challenge,
            "email": request_data.email,
            "provider": "builtin::local_magic_link",
            "callback_url": callback_url,
            "redirect_on_failure": f"{SERVER_BASE_URL}/auth/error.html"
        }
        print(f"Making request to: {register_url}")
        print(f"Request data: {request_data_log}")

        # Create headers explicitly - add Accept header as required by the API
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        print(f"Request headers: {headers}")

        register_response = await http_client.post(
            register_url,
            json=request_data_log,
            headers=headers
        )
        print(f"Response status: {register_response.status_code}")
        print(f"Response headers: {register_response.headers}")
    
    if register_response.status_code in [200, 201]:
        return {"message": "Registration magic link sent! Check your email."}
    else:
        error_text = await register_response.aread()
        raise HTTPException(status_code=400, detail=f"Registration failed: {error_text}")

@router.get("/auth/magic-link/callback")
async def magic_link_callback(
    request: Request,
    code: str = None,
    error: str = None,
    isSignUp: str = None,
    gel_pkce_verifier: str = Cookie(None)
):
    """Handle magic link callback and create User if needed."""
    if error:
        raise HTTPException(status_code=400, detail=f"Magic link error: {error}")
    if not code or not gel_pkce_verifier:
        raise HTTPException(status_code=400, detail="Missing info for magic link auth.")

    # Exchange code for token
    token_url = f"{GEL_AUTH_BASE_URL}/token"
    async with httpx.AsyncClient() as http_client:
        token_response = await http_client.get(
            token_url, 
            params={"code": code, "verifier": gel_pkce_verifier}
        )
    
    if token_response.status_code != 200:
        error_text = await token_response.aread()
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {error_text}")
    
    token_data = token_response.json()
    auth_token = token_data.get("auth_token")
    identity_id = token_data.get("identity_id")

    # If this is a signup, create the User object
    if isSignUp == "true" and identity_id:
        try:
            await client.query("""
                with identity := <ext::auth::Identity><uuid>$identity_id,
                     emailFactor := (
                         select ext::auth::EmailFactor 
                         filter .identity = identity
                     )
                insert User {
                    email := emailFactor.email,
                    name := emailFactor.email,  # Default name to email
                    identity := identity
                };
            """, identity_id=identity_id)
        except Exception as e:
            print(f"Error creating user: {e}")
            # Continue anyway - the identity exists

    response = JSONResponse(content={"message": "Authentication successful!"})
    response.set_cookie("gel-auth-token", auth_token, httponly=True, secure=True, samesite='strict')
    response.delete_cookie("gel-pkce-verifier")
    return response

@router.post("/auth/logout")
async def logout():
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("gel-auth-token")
    return response
