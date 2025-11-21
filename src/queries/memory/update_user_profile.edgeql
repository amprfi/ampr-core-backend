UPDATE userProfile::Profile
FILTER .user.id = <uuid>$userid
SET {
    country := <str>$country,
    kyc_passed := <bool>$kyc_passed,
    age_group := <userProfile::AgeGroup>$age_group,
    stated_investment_horizon := <userProfile::InvestmentHorizon>$stated_investment_horizon,
    stated_risk_appetite := <userProfile::RiskAppetite>$stated_risk_appetite,
    stated_investment_knowledge := <userProfile::InvestmentKnowledge>$stated_investment_knowledge,
    stated_financial_goals := array_unpack(<array<str>>$stated_financial_goals),
    other_investments := array_unpack(<array<str>>$other_investments),
    inferred_investment_horizon := <userProfile::InvestmentHorizon>$inferred_investment_horizon,
    inferred_risk_appetite := <userProfile::RiskAppetite>$inferred_risk_appetite,
    inferred_investment_knowledge := <userProfile::InvestmentKnowledge>$inferred_investment_knowledge,
    inferred_financial_goals := array_unpack(<array<str>>$inferred_financial_goals),
    inferred_investment_thesis := <str>$inferred_investment_thesis,
};
