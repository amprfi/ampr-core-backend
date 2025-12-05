from __future__ import annotations

import datetime
from http import HTTPStatus
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from convex import ConvexError
from src.clients.convex_client import get_client
from ..models.user import User, UserResponse
from ..models.user_profile import UserProfile

# ---------------------------------------------------------------- #

router = APIRouter()
client = get_client()


@router.get("/users")
async def get_user(
    email: str = Query(None, max_length=50), phone: str = Query(None, max_length=20)
) -> Dict[str, Any]:
    # Require exactly one parameter
    if email and phone:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"error": "Provide either email or phone, not both"},
        )
    
    if not email and not phone:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"error": "Must provide either email or phone parameter"},
        )
    
    if email:
        user = client.query("users:getUserByEmail", {"email": email})
        if not user:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail={"error": f"User with email '{email}' does not exist."},
            )
        return user
    
    # Must be phone at this point
    user = client.query("users:getUserByPhone", {"phone": phone})
    if not user:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail={"error": f"User with phone '{phone}' does not exist."},
        )
    return user


@router.get("/users/all")
async def get_all_users() -> List[Dict[str, Any]]:
    users = client.query("users:getUsers", {})
    return users


...


@router.post("/users", status_code=HTTPStatus.CREATED)
async def post_user(user: User) -> Dict[str, Any]:
    if user.first_name is None or user.last_name is None or user.email is None or user.phone is None:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"error": "Missing required fields: first_name, last_name, email, phone"},
        )

    try:
        created_user = client.mutation("users:createUser", {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": user.phone,
        })
    except ConvexError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail={"error": str(e.data)})
    return created_user


@router.post("/users/{user_id}/profile", status_code=HTTPStatus.CREATED)
async def create_user_profile(
    user_id: str, profile_data: UserProfile
) -> Dict[str, Any]:
    """
    Create a user profile for the specified user.

    Args:
        user_id: The Convex ID of the user to create a profile for
        profile_data: Profile data including country and KYC status

    Returns:
        The created profile with its ID

    Raises:
        HTTPException: If the user doesn't exist or if there's an error creating the profile
    """
    try:
        created_profile = client.mutation("profiles:createProfile", {
            "user": user_id,
            "country": profile_data.country or "",
            "kyc_passed": profile_data.kyc_passed or False,
            "age_group": profile_data.age_group,
            "stated_investment_horizon": profile_data.stated_investment_horizon,
            "stated_risk_appetite": profile_data.stated_risk_appetite,
            "stated_investment_knowledge": profile_data.stated_investment_knowledge,
            "stated_financial_goals": profile_data.stated_financial_goals,
            "other_investments": profile_data.other_investments,
            "inferred_investment_horizon": profile_data.inferred_investment_horizon,
            "inferred_risk_appetite": profile_data.inferred_risk_appetite,
            "inferred_investment_knowledge": profile_data.inferred_investment_knowledge,
            "inferred_financial_goals": profile_data.inferred_financial_goals,
            "inferred_investment_thesis": profile_data.inferred_investment_thesis,
        })
        return created_profile
    except ConvexError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail={"error": str(e.data)})
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail={"error": str(e)}
        )

@router.put("/users/{user_id}/profile")
async def update_user_profile(
    user_id: str, profile_data: UserProfile
) -> Dict[str, Any]:
    """
    Update a user profile for the specified user.
    """
    try:
        updated_profile = client.mutation("profiles:updateProfile", {
            "user": user_id,
            "country": profile_data.country,
            "kyc_passed": profile_data.kyc_passed,
            "age_group": profile_data.age_group,
            "stated_investment_horizon": profile_data.stated_investment_horizon,
            "stated_risk_appetite": profile_data.stated_risk_appetite,
            "stated_investment_knowledge": profile_data.stated_investment_knowledge,
            "stated_financial_goals": profile_data.stated_financial_goals,
            "other_investments": profile_data.other_investments,
            "inferred_investment_horizon": profile_data.inferred_investment_horizon,
            "inferred_risk_appetite": profile_data.inferred_risk_appetite,
            "inferred_investment_knowledge": profile_data.inferred_investment_knowledge,
            "inferred_financial_goals": profile_data.inferred_financial_goals,
            "inferred_investment_thesis": profile_data.inferred_investment_thesis,
        })
        return updated_profile
    except ConvexError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail={"error": str(e.data)})
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail={"error": str(e)}
        )
