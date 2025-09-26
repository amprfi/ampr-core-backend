from __future__ import annotations

import datetime
from http import HTTPStatus
from typing import List

import gel
from src.clients.gel_client import create_basic_client, ConstraintViolationError
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..queries.users import get_user_by_email_async_edgeql as get_user_by_email_qry
from ..queries.users import get_users_async_edgeql as get_users_qry
from ..queries.users import create_user_async_edgeql as create_user_qry

from ..models.user import UserCreate, UserResponse, UserUpdate

# ---------------------------------------------------------------- #

router = APIRouter()
client = create_basic_client()

class RequestData(BaseModel):
    email: str
    first_name: str
    last_name: str
    phone: str
    country: str
 
@router.get("/users")
async def get_users(
    email: str = Query(None, max_length=50)
) -> List[get_users_qry.GetUsersResult] | get_user_by_email_qry.GetUserByEmailResult:

    if not email:
        users = await get_users_qry.get_users(client)
        return users
    else:
        user = await get_user_by_email_qry.get_user_by_email(client, email=email)
        if not user:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail={"error": f"Username '{email}' does not exist."},
            )
        return user
    
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
            country=user.country
        )
    except ConstraintViolationError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": str(e)}
        )
    return created_user