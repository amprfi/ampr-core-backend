"""
Asset API endpoints.

Provides endpoints for:
- Looking up assets by ticker
- Creating individual assets
- Bulk creating assets
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..clients.convex_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class CreateAssetRequest(BaseModel):
    """Request body for creating a new asset."""
    ticker: Optional[str] = None
    name: Optional[str] = None
    liquid: bool = True
    asset_category: str  # cryptotoken, stock, currency, commodity
    price_feed: Optional[str] = None


# ============================================================================
# ASSET ENDPOINTS
# ============================================================================

@router.get("/ticker/{ticker}")
async def get_asset_by_ticker(ticker: str):
    """Look up an asset by its ticker symbol."""
    try:
        convex_client = get_client()
        asset = convex_client.query("assets:getAssetByTicker", {
            "ticker": ticker,
        })
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Asset with ticker '{ticker}' not found",
            )
        return {"asset": asset}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching asset: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


def _build_create_asset_args(request: CreateAssetRequest) -> dict:
    """Build the mutation args dict from a CreateAssetRequest."""
    args: dict = {
        "liquid": request.liquid,
        "asset_category": request.asset_category,
    }
    if request.ticker is not None:
        args["ticker"] = request.ticker
    if request.name is not None:
        args["name"] = request.name
    if request.price_feed is not None:
        args["price_feed"] = request.price_feed
    return args


@router.post("/create")
async def create_asset(request: CreateAssetRequest):
    """
    Create a new asset.

    If an asset with the same ticker already exists, returns the existing one.
    """
    try:
        convex_client = get_client()
        args = _build_create_asset_args(request)
        result = convex_client.mutation("assets:createAsset", args)
        return {"asset": result}

    except Exception as e:
        logger.error(f"Error creating asset: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/bulk-create")
async def bulk_create_assets(assets: list[CreateAssetRequest]):
    """
    Create multiple assets in one request.

    Accepts a JSON array of asset objects directly.
    Each asset is created individually. If an asset with the same ticker
    already exists, the existing one is returned for that entry.
    Returns a list of all created/existing assets.
    """
    try:
        convex_client = get_client()
        results = []
        for asset_req in assets:
            args = _build_create_asset_args(asset_req)
            result = convex_client.mutation("assets:createAsset", args)
            results.append(result)
        return {"assets": results}

    except Exception as e:
        logger.error(f"Error bulk creating assets: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
