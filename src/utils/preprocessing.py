from typing import List, Optional
from pydantic import BaseModel
from src.models.user_profile import UserProfile

def profile_to_sentences(profile: UserProfile) -> List[str]:
    sentences = []
    
    # Stated
    if profile.stated_investment_horizon:
        sentences.append(f"The user stated their investment horizon is {profile.stated_investment_horizon}.")
    if profile.stated_risk_appetite is not None:
        sentences.append(f"The user stated their risk appetite is {profile.stated_risk_appetite} (1-5).")
    if profile.stated_investment_knowledge:
        sentences.append(f"The user stated their investment knowledge is {profile.stated_investment_knowledge}.")
    if profile.stated_financial_goals:
        sentences.append(f"The user stated their financial goals are: {', '.join(profile.stated_financial_goals)}.")

    # Inferred
    if profile.inferred_investment_horizon:
        sentences.append(f"The inferred investment horizon is {profile.inferred_investment_horizon}.")
    if profile.inferred_risk_appetite is not None:
        sentences.append(f"The inferred risk appetite is {profile.inferred_risk_appetite} (1-5).")
    if profile.inferred_investment_knowledge:
        sentences.append(f"The inferred investment knowledge is {profile.inferred_investment_knowledge}.")
    if profile.inferred_financial_goals:
        sentences.append(f"The inferred financial goals are: {', '.join(profile.inferred_financial_goals)}.")
    if profile.inferred_investment_thesis:
        sentences.append(f"The inferred investment thesis is: {profile.inferred_investment_thesis}.")
        
    # Other
    if profile.age_group:
        sentences.append(f"The user's age group is {profile.age_group}.")
    if profile.other_investments:
        sentences.append(f"The user's other investments include: {', '.join(profile.other_investments)}.")
        
    return sentences
