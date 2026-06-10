"""
Country API endpoints (user-facing, read-only).

Country mutations are admin-only — see admin.py.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from src.clients.convex_client import get_client

router = APIRouter()


@router.get("/countries")
async def get_countries() -> List[Dict[str, Any]]:
    """Get all countries."""
    client = get_client()
    return client.query("countries:getCountries", {})


@router.get("/countries/{country_code}")
async def get_country(country_code: str) -> Dict[str, Any]:
    """Get a country by ISO 3166-1 alpha-3 code."""
    client = get_client()
    country = client.query("countries:getCountryByCode", {"country_code": country_code})
    if not country:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail={"error": f"Country with code '{country_code}' not found"},
        )
    return country
