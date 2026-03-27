from pydantic import BaseModel, Field
from typing import List, Optional


class Country(BaseModel):
    """Country data model for API requests."""

    country_code: str = Field(..., description="ISO 3166-1 alpha-3 country code (e.g., 'USA', 'GBR')")
    country_name: str = Field(..., description="Full country name")
    utc_offset: float = Field(..., description="UTC offset in hours (e.g., -5, 5.5)")
    calling_code: str = Field(..., description="International calling code (e.g., '1', '44')")
    ofac_country_program: bool = Field(default=False, description="Subject to OFAC country sanctions program")
    eu_asset_freeze: bool = Field(default=False, description="Subject to EU asset freeze measures")
    eu_financial_prohibition: bool = Field(default=False, description="Subject to EU financial prohibitions")
    eu_tax_haven_blacklist: bool = Field(default=False, description="On EU tax haven blacklist")
    ampersand_blocklist_full: bool = Field(default=False, description="Fully blocked by Ampersand")
    ampersand_blocklist_funding: bool = Field(default=False, description="Funding blocked by Ampersand")
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code (e.g., 'USD', 'CAD')")
    ampersand_additional_screening_required: bool = Field(default=False, description="Requires additional screening")


class CountryUpdate(BaseModel):
    """Country update model - all fields optional except country_code."""

    country_code: str = Field(..., description="ISO 3166-1 alpha-3 country code")
    country_name: Optional[str] = None
    currency: Optional[str] = None
    utc_offset: Optional[float] = None
    calling_code: Optional[str] = None
    ofac_country_program: Optional[bool] = None
    eu_asset_freeze: Optional[bool] = None
    eu_financial_prohibition: Optional[bool] = None
    eu_tax_haven_blacklist: Optional[bool] = None
    ampersand_blocklist_full: Optional[bool] = None
    ampersand_blocklist_funding: Optional[bool] = None
    ampersand_additional_screening_required: Optional[bool] = None


class BulkCountriesRequest(BaseModel):
    """Request model for bulk country upsert."""

    countries: List[Country] = Field(..., description="List of countries to insert or update")


class BulkUpsertResult(BaseModel):
    """Result of bulk upsert operation."""

    inserted: int
    updated: int
    errors: List[str]


class BulkCurrencyUpdateRequest(BaseModel):
    """Request model for bulk currency update."""

    currencies: dict[str, str] = Field(
        ...,
        description="Mapping of ISO 3166-1 alpha-3 country codes to ISO 4217 currency codes (e.g., {'USA': 'USD', 'CAN': 'CAD'})",
    )


class BulkCurrencyUpdateResult(BaseModel):
    """Result of bulk currency update operation."""

    updated: int
    errors: List[str]
