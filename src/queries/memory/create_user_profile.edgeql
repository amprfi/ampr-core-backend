INSERT userProfile::Profile {
    user := (SELECT accessControl::User FILTER .id = <uuid>$userid),
    country := <str>$country,
    kyc_passed := <bool>$kyc_passed,
    investment_horizon := <userProfile::InvestmentHorizon>$investment_horizon,
    age_group := <userProfile::AgeGroup>$age_group,
    risk_appetite := <userProfile::RiskAppetite>$risk_appetite,
    reason_for_investing := <str>$reason_for_investing,
    other_investments := array_unpack(<array<str>>$other_investments),
    investment_knowledge := <userProfile::InvestmentKnowledge>$investment_knowledge,
    financial_goals := array_unpack(<array<str>>$financial_goals)
};
