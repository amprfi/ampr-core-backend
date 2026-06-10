"""
Asset API endpoints (user-facing, read-only).

Asset creation and management are admin-only — see admin.py.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..clients.convex_client import get_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])


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
