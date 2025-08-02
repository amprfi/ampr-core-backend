from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field
from pydantic_extra_types.country import CountryAlpha3
from pydantic_extra_types.phone_numbers import PhoneNumber
from typing import Optional
from datetime import datetime
from src.services.auth_client import stytch_client
from src.services.user_service import UserService
from src.models.user import UserCreate

router = APIRouter()

# Initialize services
user_service = UserService()

class LoginPayload(BaseModel):
    email: EmailStr
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[PhoneNumber] = None
    country: Optional[CountryAlpha3] = None

@router.post("/login")
async def login(payload: LoginPayload):
    try:
        # Send magic link via Stytch
        stytch_client.magic_links.email.login_or_create(
            email=payload.email,
        )

        # Check if user exists in TypeDB, create if not
        user = await user_service.get_user_by_email(payload.email)
        if not user:
            # Create a basic user record in TypeDB with provided data or defaults
            user_data = UserCreate(
                first_name=payload.first_name or "New",
                last_name=payload.last_name or "User",
                email=payload.email,
                phone=payload.phone or "+18472840023",
                country=payload.country or "CAN",
                stytch_user_id="placeholder"  # This should be set properly when we have the Stytch user ID
            )
            await user_service.create_user(user_data)

        return {"message": "Magic link sent to your email."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AuthenticatePayload(BaseModel):
    token: str

@router.post("/authenticate")
async def authenticate(payload: AuthenticatePayload):
    try:
        # Authenticate with Stytch
        resp = stytch_client.magic_links.authenticate(
            token=payload.token,
            session_duration_minutes=60
        )

        # Get user info from Stytch
        stytch_user = stytch_client.users.get(user_id=resp.user_id)

        # Ensure user exists in TypeDB
        user = await user_service.get_user_by_email(stytch_user.email)
        if not user:
            # Create user if doesn't exist
            user_data = UserCreate(
                first_name=stytch_user.name.first_name or "New",
                last_name=stytch_user.name.last_name or "User",
                email=stytch_user.email,
                phone=stytch_user.phone_number or "+18472840023",
                country=stytch_user.country or "CAN",
                stytch_user_id=stytch_user.user_id
            )
            user = await user_service.create_user(user_data)

        return {
            "user_id": resp.user_id,
            "session_jwt": getattr(resp, 'session_jwt', ''),
            "email": stytch_user.email
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))