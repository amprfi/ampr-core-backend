from typing import List, Optional
from pydantic import BaseModel
from src.models.user_profile import UserProfile

def profile_to_sentences(profile: UserProfile) -> List[str]:
    sentences = []
    if profile.investment_horizon:
        sentences.append(f"The user's investment horizon is {profile.investment_horizon}.")
    if profile.age_group:
        sentences.append(f"The user's age group is {profile.age_group}.")
    if profile.risk_appetite is not None:
        sentences.append(f"The user's risk appetite is {profile.risk_appetite}.")
    if profile.reason_for_investing:
        sentences.append(f"The reason for investing is: {profile.reason_for_investing}.")
    if profile.other_investments:
        sentences.append(f"The user's other investments include: {', '.join(profile.other_investments)}.")
    if profile.investment_knowledge:
        sentences.append(f"The user's investment knowledge is {profile.investment_knowledge}.")
    if profile.financial_goals:
        sentences.append(f"The user's financial goals are: {', '.join(profile.financial_goals)}.")
    return sentences
