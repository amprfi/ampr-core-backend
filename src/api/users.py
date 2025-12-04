from __future__ import annotations

import datetime
import uuid
from http import HTTPStatus
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from convex import ConvexError
from src.clients.convex_client import get_client
from src.clients.gel_client import ConstraintViolationError, create_basic_client
from ..models.user import User, UserResponse
from ..models.user_profile import UserProfile
from ..queries.memory import create_user_profile_async_edgeql as create_user_profile_qry
from ..queries.memory import update_user_profile_async_edgeql as update_user_profile_qry

# ---------------------------------------------------------------- #

router = APIRouter()
client = get_client()
gel_client = create_basic_client()  # For profile queries that haven't been migrated yet


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
    user_id: uuid.UUID, profile_data: UserProfile
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
        stated_horizon = (
            create_user_profile_qry.UserprofileInvestmentHorizon(
                profile_data.stated_investment_horizon
            )
            if profile_data.stated_investment_horizon
            else None
        )
        stated_risk = profile_data.stated_risk_appetite
        stated_knowledge = (
            create_user_profile_qry.UserprofileInvestmentKnowledge(
                profile_data.stated_investment_knowledge
            )
            if profile_data.stated_investment_knowledge
            else None
        )
        stated_goals = profile_data.stated_financial_goals or []

        # Note: Inferred values are initialized as None/Blank until populated by extractor agent
        inferred_horizon = (
            create_user_profile_qry.UserprofileInvestmentHorizon(
                profile_data.inferred_investment_horizon
            )
            if profile_data.inferred_investment_horizon
            else None
        )
        inferred_risk = profile_data.inferred_risk_appetite
        inferred_knowledge = (
            create_user_profile_qry.UserprofileInvestmentKnowledge(
                profile_data.inferred_investment_knowledge
            )
            if profile_data.inferred_investment_knowledge
            else None
        )
        inferred_goals = profile_data.inferred_financial_goals or []
        inferred_thesis = profile_data.inferred_investment_thesis or ""

        result = await create_user_profile_qry.create_user_profile(
            executor=gel_client,
            userid=user_id,
            country=profile_data.country or "",
            kyc_passed=profile_data.kyc_passed or False,
            age_group=create_user_profile_qry.UserprofileAgeGroup(profile_data.age_group)
            if profile_data.age_group
            else None,
            stated_investment_horizon=stated_horizon,
            stated_risk_appetite=stated_risk,
            stated_investment_knowledge=stated_knowledge,
            stated_financial_goals=stated_goals,
            other_investments=profile_data.other_investments or [],
            inferred_investment_horizon=inferred_horizon,
            inferred_risk_appetite=inferred_risk,
            inferred_investment_knowledge=inferred_knowledge,
            inferred_financial_goals=inferred_goals,
            inferred_investment_thesis=inferred_thesis,
        )

        return result

    except ConstraintViolationError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail={"error": str(e)})
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail={"error": str(e)}
        )

@router.put("/users/{user_id}/profile")
async def update_user_profile(
    user_id: uuid.UUID, profile_data: UserProfile
) -> List[update_user_profile_qry.UpdateUserProfileResult]:
    """
    Update a user profile for the specified user.
    """
    try:
        # Update the user profile
        stated_horizon = (
            update_user_profile_qry.UserprofileInvestmentHorizon(
                profile_data.stated_investment_horizon
            )
            if profile_data.stated_investment_horizon
            else None
        )
        stated_risk = profile_data.stated_risk_appetite
        stated_knowledge = (
            update_user_profile_qry.UserprofileInvestmentKnowledge(
                profile_data.stated_investment_knowledge
            )
            if profile_data.stated_investment_knowledge
            else None
        )
        stated_goals = profile_data.stated_financial_goals or []

        inferred_horizon = (
            update_user_profile_qry.UserprofileInvestmentHorizon(
                profile_data.inferred_investment_horizon
            )
            if profile_data.inferred_investment_horizon
            else None
        )
        inferred_risk = profile_data.inferred_risk_appetite
        inferred_knowledge = (
            update_user_profile_qry.UserprofileInvestmentKnowledge(
                profile_data.inferred_investment_knowledge
            )
            if profile_data.inferred_investment_knowledge
            else None
        )
        inferred_goals = profile_data.inferred_financial_goals or []
        inferred_thesis = profile_data.inferred_investment_thesis or ""

        result = await update_user_profile_qry.update_user_profile(
            executor=gel_client,
            userid=user_id,
            country=profile_data.country or "",
            kyc_passed=profile_data.kyc_passed or False,
            age_group=update_user_profile_qry.UserprofileAgeGroup(profile_data.age_group)
            if profile_data.age_group
            else None,
            stated_investment_horizon=stated_horizon,
            stated_risk_appetite=stated_risk,
            stated_investment_knowledge=stated_knowledge,
            stated_financial_goals=stated_goals,
            other_investments=profile_data.other_investments or [],
            inferred_investment_horizon=inferred_horizon,
            inferred_risk_appetite=inferred_risk,
            inferred_investment_knowledge=inferred_knowledge,
            inferred_financial_goals=inferred_goals,
            inferred_investment_thesis=inferred_thesis,
        )

        return result

    except ConstraintViolationError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail={"error": str(e)})
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail={"error": str(e)}
        )
