select userProfile::Profile {
    investment_horizon,
    age_group,
    risk_appetite,
    reason_for_investing,
    other_investments,
    investment_knowledge,
    financial_goals
}
filter .user.id = <uuid>$user_id
limit 1
