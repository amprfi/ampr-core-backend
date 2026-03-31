from typing import Annotated, List, Literal, Optional
from pydantic import BaseModel, Field

class UserProfile(BaseModel):
    country: Optional[str] = Field(None, description="Convex ID of the country record")
    kyc_passed: Optional[bool] = False
    stated_risk_appetite: Optional[Annotated[int, Field(ge=1, le=5)]] = None
    stated_investment_horizon: Optional[Literal["1-5", "6-10", "10-20", "20 plus"]] = None
    age_group: Optional[Literal["under25", "25-34", "35-44", "45-54", "55plus"]] = None
    other_investments: Optional[List[str]] = None
    stated_investment_knowledge: Optional[Literal["novice", "intermediate", "advanced"]] = None
    stated_financial_goals: Optional[List[str]] = None
    inferred_risk_appetite: Optional[Annotated[int, Field(ge=1, le=5)]] = None
    inferred_investment_horizon: Optional[Literal["1-5", "6-10", "10-20", "20 plus"]] = None
    inferred_investment_knowledge: Optional[Literal["novice", "intermediate", "advanced"]] = None
    inferred_financial_goals: Optional[List[str]] = None
    inferred_investment_thesis: Optional[str] = None
    preferred_currency: Optional[str] = Field(None, description="ISO 4217 currency code (e.g., USD, CAD)")
