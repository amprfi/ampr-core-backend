select userProfile::Profile {
    stated_investment_horizon,
    inferred_investment_horizon,
    stated_risk_appetite,
    inferred_risk_appetite,
    stated_investment_knowledge,
    inferred_investment_knowledge,
    stated_financial_goals,
    inferred_financial_goals,
    other_investments,
    inferred_investment_thesis
}
filter .user.id = <uuid>$user_id
limit 1
