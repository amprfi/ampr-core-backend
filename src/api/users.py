"""
User API endpoints (user-facing).

All endpoints require Hanko authentication via the middleware.
User IDs are injected from the authenticated session — callers cannot
specify arbitrary user IDs.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from convex import ConvexError

from src.clients.convex_client import get_client
from src.middleware.auth import get_current_user_id
from ..models.user_profile import UserProfile

# ---------------------------------------------------------------- #

router = APIRouter()


@router.get("/users/me")
async def get_current_user(
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Return the authenticated user's own record."""
    client = get_client()
    user = client.query("users:getUser", {"userId": user_id})
    if not user:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail={"error": "User not found"},
        )
    return user


@router.post("/users/me/profile", status_code=HTTPStatus.CREATED)
async def create_user_profile(
    profile_data: UserProfile,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Create a profile for the authenticated user."""
    try:
        client = get_client()
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


@router.put("/users/me/profile")
async def update_user_profile(
    profile_data: UserProfile,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """Update the authenticated user's profile."""
    try:
        client = get_client()
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
