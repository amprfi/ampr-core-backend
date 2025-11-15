CREATE MIGRATION m1fcj22bmvt4u3zo6x76lcp6s7khw4gyrvplbkdob6kaffz2yagvca
    ONTO m1luw2a2ngfqxd5fqpcd36upkysxkwkcj3u4wxj4vrtzap6flzitja
{
  CREATE SCALAR TYPE userProfile::AgeGroup EXTENDING enum<under25, `25-34`, `35-44`, `45-54`, `55plus`>;
  CREATE SCALAR TYPE userProfile::InvestmentHorizon EXTENDING enum<`1-5`, `6-10`, `10-20`, `20plus`>;
  CREATE SCALAR TYPE userProfile::InvestmentKnowledge EXTENDING enum<novice, intermediate, advanced>;
  ALTER TYPE userProfile::Profile {
      CREATE PROPERTY age_group: userProfile::AgeGroup;
      CREATE MULTI PROPERTY financial_goals: std::str;
      CREATE PROPERTY investment_horizon: userProfile::InvestmentHorizon;
      CREATE PROPERTY investment_knowledge: userProfile::InvestmentKnowledge;
      CREATE MULTI PROPERTY other_investments: std::str;
      CREATE PROPERTY reason_for_investing: std::str;
      CREATE PROPERTY risk_appetite: std::int16;
  };
};
