from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from src.services.auth_client import stytch_client
from src.services.user_service import UserService
from src.models.user import UserCreate

router = APIRouter()

# Initialize services
user_service = UserService()

class LoginPayload(BaseModel):
    email: str

@router.post("/login")
def login(payload: LoginPayload):
    try:
        # Send magic link via Stytch
        stytch_client.magic_links.email.login_or_create(
            email=payload.email,
        )

        # Check if user exists in TypeDB, create if not
        user = user_service.get_user_by_email(payload.email)
        if not user:
            # Create a basic user record in TypeDB
            user_data = UserCreate(
                first_name="New",
                last_name="User",
                email=payload.email,
                phone="",
                country="",
                stytch_user_id="placeholder"  # This should be set properly when we have the Stytch user ID
            )
            user_service.create_user(user_data)

        return {"message": "Magic link sent to your email."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AuthenticatePayload(BaseModel):
    token: str

@router.post("/authenticate")
def authenticate(payload: AuthenticatePayload):
    try:
        # Authenticate with Stytch
        resp = stytch_client.magic_links.authenticate(
            token=payload.token,
            session_duration_minutes=60
        )

        # Get user info from Stytch
        stytch_user = stytch_client.users.get(user_id=resp.user_id)

        # Ensure user exists in TypeDB
        user = user_service.get_user_by_email(stytch_user.email)
        if not user:
            # Create user if doesn't exist
            user_data = UserCreate(
                first_name=stytch_user.name.first_name or "New",
                last_name=stytch_user.name.last_name or "User",
                email=stytch_user.email,
                phone=stytch_user.phone_number or "",
                country=stytch_user.country or "",
                stytch_user_id=stytch_user.user_id
            )
            user = user_service.create_user(user_data)

        return {
            "user_id": resp.user_id,
            "session_jwt": getattr(resp, 'session_jwt', ''),
            "email": stytch_user.email
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))