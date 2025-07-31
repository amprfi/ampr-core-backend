from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from src.services.auth_client import stytch_client

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/authenticate")

def get_authenticated_session(token: str = Depends(oauth2_scheme)):
    try:
        # Authenticate the session JWT with Stytch
        response = stytch_client.sessions.authenticate_jwt(
            session_jwt=token,
        )
        return response
    except Exception as e:
        # If the token is invalid, raise an exception
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )