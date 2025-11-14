from __future__ import annotations

import datetime
from http import HTTPStatus
from typing import List
import uuid

from src.clients.gel_client import create_basic_client, ConstraintViolationError
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..queries.users import get_user_by_email_async_edgeql as get_user_by_email_qry
from ..queries.users import get_users_async_edgeql as get_users_qry
from ..queries.users import create_user_async_edgeql as create_user_qry
from ..queries.users import get_user_by_phone_async_edgeql as get_user_by_phone_qry
from ..queries.memory import create_user_profile_async_edgeql as create_user_profile_qry

from ..models.user import UserCreate, UserResponse, UserUpdate

# ---------------------------------------------------------------- #

router = APIRouter()
client = create_basic_client()

class RequestData(BaseModel):
    email: str
    first_name: str
    last_name: str
    phone: str

class UserProfileCreate(BaseModel):
    country: str
    kyc_passed: bool = False
 
@router.get("/users")
async def get_users(
    email: str = Query(None, max_length=50),
    phone: str = Query(None, max_length=20)
) -> List[get_users_qry.GetUsersResult] | get_user_by_email_qry.GetUserByEmailResult | get_user_by_phone_qry.GetUserByPhoneResult:

    if email:
        user = await get_user_by_email_qry.get_user_by_email(client, email=email)
        if not user:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail={"error": f"Username '{email}' does not exist."},
            )
        return user
    elif phone:
        user = await get_user_by_phone_qry.get_user_by_phone(client, phone=phone)
        if not user:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail={"error": f"User with phone '{phone}' does not exist."},
            )
        return user
    else:
        users = await get_users_qry.get_users(client)
        return users
    
...
@router.post("/users", status_code=HTTPStatus.CREATED)
async def post_user(user: RequestData) -> create_user_qry.CreateUserResult:

    try:
        created_user = await create_user_qry.create_user(
            client,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            phone=user.phone,
        )
    except ConstraintViolationError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": str(e)}
        )
    return created_user

@router.post("/users/{user_id}/profile", status_code=HTTPStatus.CREATED)
async def create_user_profile(
    user_id: uuid.UUID,
    profile_data: UserProfileCreate
) -> create_user_profile_qry.CreateUserProfileResult:
    """
    Create a user profile for the specified user.

    Args:
        user_id: The UUID of the user to create a profile for
        profile_data: Profile data including country and KYC status

    Returns:
        The created profile with its ID

    Raises:
        HTTPException: If the user doesn't exist or if there's an error creating the profile
    """
    try:

        # Create the user profile
        result = await create_user_profile_qry.create_user_profile(
            executor=client,
            userid=user_id,
            country=profile_data.country,
            kyc_passed=profile_data.kyc_passed
        )

        return result

    except ConstraintViolationError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": str(e)}
        )
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail={"error": str(e)}
        )