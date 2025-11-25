UPDATE userProfile::Profile
FILTER .user.id = <uuid>$userid
SET {
    country := <optional str>$country ?? .country,
    kyc_passed := <optional bool>$kyc_passed ?? .kyc_passed,
    age_group := <optional userProfile::AgeGroup>$age_group ?? .age_group,
    stated_investment_horizon := <optional userProfile::InvestmentHorizon>$stated_investment_horizon ?? .stated_investment_horizon,
    stated_risk_appetite := <optional userProfile::RiskAppetite>$stated_risk_appetite ?? .stated_risk_appetite,
    stated_investment_knowledge := <optional userProfile::InvestmentKnowledge>$stated_investment_knowledge ?? .stated_investment_knowledge,
    stated_financial_goals := (
        array_unpack(<optional array<str>>$stated_financial_goals)
        IF EXISTS <optional array<str>>$stated_financial_goals
        ELSE .stated_financial_goals
    ),
    other_investments := (
        array_unpack(<optional array<str>>$other_investments)
        IF EXISTS <optional array<str>>$other_investments
        ELSE .other_investments
    ),
    inferred_investment_horizon := <optional userProfile::InvestmentHorizon>$inferred_investment_horizon ?? .inferred_investment_horizon,
    inferred_risk_appetite := <optional userProfile::RiskAppetite>$inferred_risk_appetite ?? .inferred_risk_appetite,
    inferred_investment_knowledge := <optional userProfile::InvestmentKnowledge>$inferred_investment_knowledge ?? .inferred_investment_knowledge,
    inferred_financial_goals := (
        DISTINCT (
            .inferred_financial_goals UNION array_unpack(<optional array<str>>$inferred_financial_goals)
        )
        IF EXISTS <optional array<str>>$inferred_financial_goals
        ELSE .inferred_financial_goals
    ),
    inferred_investment_thesis := <optional str>$inferred_investment_thesis ?? .inferred_investment_thesis,
};
