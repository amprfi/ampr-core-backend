"""
Watchlist API endpoints (user-facing).

All endpoints require Hanko authentication. User IDs are injected
from the authenticated session — callers cannot specify arbitrary user IDs.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends, status
from pydantic import BaseModel

from src.middleware.auth import get_current_user_id
from ..clients.convex_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

# Allowed values for the `types` query parameter on GET /watchlist.
_VALID_WATCHLIST_TYPES = {"asset", "event"}


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class AddToWatchlistRequest(BaseModel):
    """Request body for adding an asset to watchlist."""
    asset_id: str


class RemoveFromWatchlistRequest(BaseModel):
    """Request body for removing an asset from watchlist."""
    asset_id: str


class UpdateAssetStatusRequest(BaseModel):
    """Request body for updating asset status."""
    asset_id: str
    asset_status: str  # "pending inferred watch", "inferred watch", "stated watch", "owned"


# ============================================================================
# WATCHLIST ENDPOINTS
# ============================================================================

@router.get("")
async def get_watchlist(
    types: Optional[str] = Query(
        default=None,
        description=(
            "Comma-separated list of watchlist types to include. "
            "Allowed values: 'asset', 'event'. Defaults to all types."
        ),
        examples=["asset", "event", "asset,event"],
    ),
    user_id: str = Depends(get_current_user_id),
):
    """Get the authenticated user's watchlist(s)."""
    # Parse + validate the `types` query parameter
    if types is None:
        requested = set(_VALID_WATCHLIST_TYPES)
    else:
        requested = {t.strip().lower() for t in types.split(",") if t.strip()}
        invalid = requested - _VALID_WATCHLIST_TYPES
        if invalid or not requested:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid watchlist type(s): {sorted(invalid) or 'none provided'}. "
                    f"Valid values: {sorted(_VALID_WATCHLIST_TYPES)}."
                ),
            )

    try:
        convex_client = get_client()
        response: dict = {}
        if "asset" in requested:
            response["assets"] = convex_client.query(
                "portfolioItems:getWatchlist", {"user": user_id}
            ) or []
        if "event" in requested:
            response["events"] = convex_client.query(
                "watchlistEvents:getWatchlistByUser", {"user": user_id}
            ) or []
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/portfolio")
async def get_portfolio(user_id: str = Depends(get_current_user_id)):
    """Get all portfolio items for the authenticated user."""
    try:
        convex_client = get_client()
        items = convex_client.query("portfolioItems:getPortfolioByUser", {
            "user": user_id,
        })
        return {"portfolio": items}

    except Exception as e:
        logger.error(f"Error fetching portfolio: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/owned")
async def get_owned_assets(user_id: str = Depends(get_current_user_id)):
    """Get owned assets for the authenticated user."""
    try:
        convex_client = get_client()
        items = convex_client.query("portfolioItems:getOwnedAssets", {
            "user": user_id,
        })
        return {"owned_assets": items}

    except Exception as e:
        logger.error(f"Error fetching owned assets: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/add")
async def add_to_watchlist(
    request: AddToWatchlistRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Add an asset to the authenticated user's watchlist."""
    try:
        convex_client = get_client()
        result = convex_client.mutation("portfolioItems:addToWatchlist", {
            "user": user_id,
            "asset": request.asset_id,
        })
        return {"item": result}

    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/remove")
async def remove_from_watchlist(
    request: RemoveFromWatchlistRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Remove an asset from the authenticated user's watchlist."""
    try:
        convex_client = get_client()
        convex_client.mutation("portfolioItems:removeFromWatchlist", {
            "user": user_id,
            "asset": request.asset_id,
        })
        return {"success": True}

    except Exception as e:
        logger.error(f"Error removing from watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/status")
async def update_asset_status(
    request: UpdateAssetStatusRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Update the status of a portfolio item for the authenticated user."""
    try:
        convex_client = get_client()
        result = convex_client.mutation("portfolioItems:updateAssetStatus", {
            "user": user_id,
            "asset": request.asset_id,
            "asset_status": request.asset_status,
        })
        return {"item": result}

    except Exception as e:
        logger.error(f"Error updating asset status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
