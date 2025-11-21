CREATE MIGRATION m1udombecmmaurmsvk7l7cug4j2x37nlml5xz2cqq5eu4zfb2sml4q
    ONTO m1owdgi27dg566y3tk3xomuaa2bh4h3njszzae26rjqbxvpeuh4e3a
{
  CREATE MODULE assets IF NOT EXISTS;
  CREATE SCALAR TYPE assets::AssetCategory EXTENDING enum<cryptotoken, stock, currency, commodity>;
  CREATE TYPE assets::asset {
      CREATE REQUIRED PROPERTY asset_category: assets::AssetCategory;
      CREATE REQUIRED PROPERTY liquid: std::bool {
          SET default := false;
      };
      CREATE PROPERTY name: std::str;
      CREATE PROPERTY ticker: std::str;
  };
  ALTER TYPE userProfile::WatchList {
      CREATE MULTI LINK assets: assets::asset {
          CREATE PROPERTY is_inferred: std::bool;
      };
  };
  ALTER TYPE userProfile::Profile {
      ALTER PROPERTY financial_goals {
          RENAME TO inferred_financial_goals;
      };
  };
  ALTER TYPE userProfile::Profile {
      CREATE PROPERTY inferred_risk_appetite: userProfile::RiskAppetite;
  };
  ALTER TYPE userProfile::Profile {
      ALTER PROPERTY investment_horizon {
          RENAME TO inferred_investment_horizon;
      };
  };
  ALTER TYPE userProfile::Profile {
      ALTER PROPERTY investment_knowledge {
          RENAME TO inferred_investment_knowledge;
      };
  };
  ALTER TYPE userProfile::Profile {
      ALTER PROPERTY reason_for_investing {
          RENAME TO inferred_investment_thesis;
      };
  };
  ALTER TYPE userProfile::Profile {
      DROP PROPERTY risk_appetite;
  };
  ALTER TYPE userProfile::Profile {
      CREATE MULTI PROPERTY stated_financial_goals: std::str;
  };
  ALTER TYPE userProfile::Profile {
      CREATE PROPERTY stated_investment_horizon: userProfile::InvestmentHorizon;
  };
  ALTER TYPE userProfile::Profile {
      CREATE PROPERTY stated_investment_knowledge: userProfile::InvestmentKnowledge;
  };
  ALTER TYPE userProfile::Profile {
      CREATE PROPERTY stated_risk_appetite: userProfile::RiskAppetite;
  };
};
