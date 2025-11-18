from typing import Annotated, List, Literal, Optional
from pydantic import BaseModel, Field, validator
from pydantic_extra_types.country import CountryAlpha3

class UserProfile(BaseModel):
    country: Optional[CountryAlpha3]
    kyc_passed: Optional[bool] = False
    risk_appetite: Optional[Annotated[int, Field(ge=1, le=5)]]
    investment_horizon: Optional[Literal["1-5", "6-10", "10-20", "20plus"]]
    age_group: Optional[Literal["under25", "25-34", "35-44", "45-54", "55plus"]]
    reason_for_investing: Optional[str]
    other_investments: Optional[List[str]]
    investment_knowledge: Optional[Literal["novice", "intermediate", "advanced"]]
    financial_goals: Optional[List[str]]
