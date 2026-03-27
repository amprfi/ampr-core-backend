from __future__ import annotations

from http import HTTPStatus
from typing import Any, Dict, List

from convex import ConvexError
from fastapi import APIRouter, HTTPException

from src.clients.convex_client import get_client
from src.models.country import (
    BulkCountriesRequest,
    BulkCurrencyUpdateRequest,
    BulkCurrencyUpdateResult,
    BulkUpsertResult,
    Country,
    CountryUpdate,
)

router = APIRouter()
client = get_client()


@router.get("/countries")
async def get_countries() -> List[Dict[str, Any]]:
    """Get all countries."""
    return client.query("countries:getCountries", {})


@router.get("/countries/{country_code}")
async def get_country(country_code: str) -> Dict[str, Any]:
    """Get a country by ISO 3166-1 alpha-3 code."""
    country = client.query("countries:getCountryByCode", {"country_code": country_code})
    if not country:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail={"error": f"Country with code '{country_code}' not found"},
        )
    return country


@router.post("/countries", status_code=HTTPStatus.CREATED)
async def create_country(country: Country) -> Dict[str, Any]:
    """Create a new country."""
    try:
        return client.mutation("countries:createCountry", country.model_dump())
    except ConvexError as e:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"error": str(e.data)},
        )


@router.post("/countries/bulk", status_code=HTTPStatus.OK)
async def bulk_upsert_countries(request: BulkCountriesRequest) -> BulkUpsertResult:
    """
    Bulk insert or update countries.

    Upserts based on country_code - inserts new records or updates existing ones.
    """
    try:
        countries_data = [c.model_dump() for c in request.countries]
        result = client.mutation("countries:bulkUpsertCountries", {"countries": countries_data})
        return BulkUpsertResult(**result)
    except ConvexError as e:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"error": str(e.data)},
        )


@router.put("/countries/bulk-currencies")
async def bulk_update_currencies(request: BulkCurrencyUpdateRequest) -> BulkCurrencyUpdateResult:
    """
    Bulk update currency codes on existing country records.

    Accepts a mapping of country codes to currency codes and updates each country.
    """
    updated = 0
    errors: List[str] = []

    for country_code, currency in request.currencies.items():
        try:
            client.mutation(
                "countries:updateCountry",
                {"country_code": country_code, "currency": currency},
            )
            updated += 1
        except ConvexError as e:
            errors.append(f"{country_code}: {str(e.data)}")
        except Exception as e:
            errors.append(f"{country_code}: {str(e)}")

    return BulkCurrencyUpdateResult(updated=updated, errors=errors)


@router.put("/countries/{country_code}")
async def update_country(country_code: str, country: CountryUpdate) -> Dict[str, Any]:
    """Update an existing country."""
    if country.country_code.upper() != country_code.upper():
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"error": "country_code in path and body must match"},
        )

    update_data = {k: v for k, v in country.model_dump().items() if v is not None}

    try:
        return client.mutation("countries:updateCountry", update_data)
    except ConvexError as e:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"error": str(e.data)},
        )


@router.delete("/countries/{country_code}")
async def delete_country(country_code: str) -> Dict[str, Any]:
    """Delete a country by code."""
    try:
        return client.mutation("countries:deleteCountry", {"country_code": country_code})
    except ConvexError as e:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"error": str(e.data)},
        )
