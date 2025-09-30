import os
import secrets
import hashlib
import base64
import httpx
from fastapi import APIRouter, Response, Request, HTTPException, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from pydantic_extra_types.country import CountryAlpha3
from pydantic_extra_types.phone_numbers import PhoneNumber
from src.clients.gel_client import create_basic_client, create_authenticated_client, AuthenticationError, ConstraintViolationError
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gel import AsyncIOClient

from dotenv import load_dotenv
load_dotenv()

from ..queries.users import create_user_async_edgeql as create_user_qry
from ..queries.users import get_user_by_email_async_edgeql as get_user_by_email_qry

router = APIRouter()

client = create_basic_client()
GEL_AUTH_BASE_URL = os.getenv("GEL_AUTH_BASE_URL")
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000/api")

def get_auth_token_from_request(request: Request) -> str:
    """Extract the auth token from cookies or headers in the request."""
    auth_token = request.cookies.get("gel-auth-token")

    if not auth_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ")[1]
        elif not auth_token:
            auth_token = request.headers.get("X-Gel-Auth-Token")

    if not auth_token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in first."
        )

    return auth_token

def get_configured_client(request: Request) -> 'AsyncIOClient':
    """Configure the Gel client with the auth token from the request."""
    auth_token = get_auth_token_from_request(request)
    return create_authenticated_client(auth_token)

class MagicLinkRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: PhoneNumber
    country: CountryAlpha3

class MagicLinkLoginRequest(BaseModel):
    email: EmailStr

def generate_pkce():
    verifier = secrets.token_urlsafe(32)
    challenge = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(challenge).decode('utf-8').rstrip('=')

@router.post("/auth/magic-link/send")
async def request_magic_link(request_data: MagicLinkLoginRequest, response: Response):
    """Request a magic link for EXISTING users (sign-in)."""
    # First check if user exists in our database
    user = await get_user_by_email_qry.get_user_by_email(client, email=request_data.email)

    if user is None:
        # User doesn't exist in our database
        raise HTTPException(
            status_code=404,
            detail="User not found. Please sign up first."
        )

    verifier, challenge = generate_pkce()
    # Store verifier in callback URL instead of cookie
    callback_url = f"{SERVER_BASE_URL}/auth/magic-link/callback?isSignUp=false"
    callback_url += f"&verifier={verifier}"

    email_url = f"{GEL_AUTH_BASE_URL}/magic-link/email"

    async with httpx.AsyncClient() as http_client:
        magic_link_response = await http_client.post(
            email_url,
            json={
                "challenge": challenge,
                "email": request_data.email,
                "provider": "builtin::local_magic_link",
                "callback_url": callback_url,
                "redirect_on_failure": f"{SERVER_BASE_URL}/auth/error.html"
            }
        )

    # Log the response for debugging
    print(f"GEL auth response status: {magic_link_response.status_code}")
    print(f"GEL auth response body: {await magic_link_response.aread()}")

    if magic_link_response.status_code == 200:
        return {"message": "Magic link sent! Check your email."}
    else:
        # Handle different error cases from GEL auth
        error_body = await magic_link_response.aread()
        print(f"GEL auth error: {error_body}")
        raise HTTPException(
            status_code=magic_link_response.status_code,
            detail=f"Authentication error: {error_body.decode('utf-8') if isinstance(error_body, bytes) else error_body}"
        )

@router.post("/auth/magic-link/signup")
async def signup_magic_link(request_data: MagicLinkRequest, response: Response):
    """Register a NEW user with magic link."""
    phone_str = str(request_data.phone)
    country_str = str(request_data.country)

    print(f"Phone object type: {type(request_data.phone)}, value: {request_data.phone}")

    verifier, challenge = generate_pkce()
    # Store verifier in callback URL instead of cookie
    callback_url = f"{SERVER_BASE_URL}/auth/magic-link/callback?isSignUp=true"
    callback_url += f"&first_name={request_data.first_name}&last_name={request_data.last_name}"
    callback_url += f"&phone={phone_str}&country={country_str}"
    callback_url += f"&verifier={verifier}"

    register_url = f"{GEL_AUTH_BASE_URL}/magic-link/register"
    
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
    first_name: str = None,
    last_name: str = None,
    phone: str = None,
    country: str = None,
    verifier: str = None
):
    """Handle magic link callback and create User if needed."""
    if error:
        raise HTTPException(status_code=400, detail=f"Magic link error: {error}")
    if not code or not verifier:
        raise HTTPException(status_code=400, detail="Missing info for magic link auth.")

    # Exchange code for token
    token_url = f"{GEL_AUTH_BASE_URL}/token"
    async with httpx.AsyncClient() as http_client:
        token_response = await http_client.get(
            token_url,
            params={"code": code, "verifier": verifier}
        )

    if token_response.status_code != 200:
        error_text = await token_response.aread()
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {error_text}")

    token_data = token_response.json()
    auth_token = token_data.get("auth_token")
    identity_id = token_data.get("identity_id")

    # Create a configured client with the auth token
    gel_client = create_authenticated_client(auth_token)

    # If this is a signup, create the User object
    if isSignUp == "true" and identity_id:
        try:
            # Get the email from the identity
            print(f"Getting email for identity_id: {identity_id}")
            email = await gel_client.query_single("""
            with identity := <ext::auth::Identity><uuid>$identity_id
            select (
                select ext::auth::EmailFactor
                filter .identity = identity
                limit 1
            ).email
            """, identity_id=identity_id)
            print(f"Retrieved email: {email}")

            # Clean up the phone number to match the database format
            clean_phone = phone.replace("tel: ", "").replace(" ", "").replace("-", "")
            print(f"Cleaned phone number: {clean_phone}")

            # Create user using the same pattern as the working user creation
            try:
                print(f"Attempting to create user with: first_name={first_name}, last_name={last_name}, email={email}, phone={clean_phone}, country={country}")
                created_user = await create_user_qry.create_user(
                    gel_client,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=clean_phone,
                    country=country
                )
                print(f"User created successfully: {created_user}")

                # Link the user to the identity
                print(f"Linking user {created_user.id} to identity {identity_id}")
                await gel_client.query_single("""
                with
                    user := <accessControl::User><uuid>$user_id,
                    identity := <ext::auth::Identity><uuid>$identity_id
                select user {
                    identity := identity
                }
                """, user_id=created_user.id, identity_id=identity_id)
                print(f"User linked to identity successfully")

                # Redirect to a success page
                response = JSONResponse(content={"message": "Signup successful! You can now log in."})
                response.set_cookie("gel-auth-token", auth_token, httponly=True, secure=True, samesite='strict')
                response.delete_cookie("gel-pkce-verifier")
                return response
            except ConstraintViolationError as e:
                print(f"Constraint violation when creating user: {e}")
                # This means the user already exists, try to link to identity
                try:
                    # Try to find the existing user by email
                    existing_user = await gel_client.query_single("""
                    select User
                    filter .email = <str>$email
                    limit 1
                    """, email=email)
                    if existing_user:
                        print(f"Found existing user: {existing_user.id}, linking to identity")
                        # Link the existing user to the identity
                        await gel_client.query_single("""
                        with
                            user := <accessControl::User><uuid>$user_id,
                            identity := <ext::auth::Identity><uuid>$identity_id
                        select user {
                            identity := identity
                        }
                        """, user_id=existing_user.id, identity_id=identity_id)
                        print(f"Existing user linked to identity successfully")
                except Exception as link_e:
                    print(f"Error linking existing user to identity: {link_e}")
            except Exception as e:
                print(f"Error creating user: {e}")
                # Continue anyway - the identity exists
        except Exception as e:
            print(f"Error getting email: {e}")
            # Continue anyway - the identity exists

    # For login, just set the auth token
    response = JSONResponse(content={"message": "Authentication successful!"})
    response.set_cookie("gel-auth-token", auth_token, httponly=True, secure=True, samesite='strict')
    response.delete_cookie("gel-pkce-verifier")
    return response

@router.post("/auth/logout")
async def logout():
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("gel-auth-token")
    return response
