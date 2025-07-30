from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.services.auth_client import stytch_client

router = APIRouter()

class LoginPayload(BaseModel):
    email: str

@router.post("/login")
def login(payload: LoginPayload):
    try:
        stytch_client.magic_links.email.login_or_create(
            email=payload.email,
        )
        return {"message": "Magic link sent to your email."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AuthenticatePayload(BaseModel):
    token: str

@router.post("/authenticate")
def authenticate(payload: AuthenticatePayload):
    try:
        resp = stytch_client.magic_links.authenticate(
            token=payload.token,
            session_duration_minutes=60
        )
        return {
            "user_id": resp.user_id,
            "session_jwt": getattr(resp, 'session_jwt', '')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))