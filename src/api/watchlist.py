"""
Watchlist API endpoints.

Provides endpoints for:
- Viewing a user's watchlist and portfolio
- Adding/removing assets from watchlist
- Managing assets
"""

import logging
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..clients.convex_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class AddToWatchlistRequest(BaseModel):
    """Request body for adding an asset to watchlist."""
    user_id: str
    asset_id: str


class RemoveFromWatchlistRequest(BaseModel):
    """Request body for removing an asset from watchlist."""
    user_id: str
    asset_id: str


class UpdateAssetStatusRequest(BaseModel):
    """Request body for updating asset status."""
    user_id: str
    asset_id: str
    asset_status: str  # "pending inferred watch", "inferred watch", "stated watch", "owned"


# ============================================================================
# WATCHLIST ENDPOINTS
# ============================================================================

@router.get("/{user_id}")
async def get_watchlist(user_id: str):
    """Get all watchlist items for a user (stated + inferred watches)."""
    try:
        convex_client = get_client()
        items = convex_client.query("portfolioItems:getWatchlist", {
            "user": user_id,
        })
        return {"watchlist": items}

    except Exception as e:
        logger.error(f"Error fetching watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/portfolio/{user_id}")
async def get_portfolio(user_id: str):
    """Get all portfolio items for a user (all statuses)."""
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


@router.get("/owned/{user_id}")
async def get_owned_assets(user_id: str):
    """Get owned assets for a user."""
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
async def add_to_watchlist(request: AddToWatchlistRequest):
    """
    Add an asset to a user's watchlist.
    
    If the asset was previously an inferred watch, upgrades to stated watch.
    If already watched or owned, returns existing item.
    """
    try:
        convex_client = get_client()
        result = convex_client.mutation("portfolioItems:addToWatchlist", {
            "user": request.user_id,
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
async def remove_from_watchlist(request: RemoveFromWatchlistRequest):
    """
    Remove an asset from a user's watchlist.
    
    Cannot remove owned assets — only watches.
    """
    try:
        convex_client = get_client()
        convex_client.mutation("portfolioItems:removeFromWatchlist", {
            "user": request.user_id,
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
async def update_asset_status(request: UpdateAssetStatusRequest):
    """Update the status of a portfolio item."""
    try:
        convex_client = get_client()
        result = convex_client.mutation("portfolioItems:updateAssetStatus", {
            "user": request.user_id,
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



