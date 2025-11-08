CREATE MIGRATION m1kluo2lmg244mjqokwusrnnk34zh7a2xlrmbcxqbgswkxqjcku7pa
    ONTO m13i2nrskufcvquxyleqvk67qblhl44mesuneqsfuoohtknsw6nj5a
{
  CREATE MODULE userProfile IF NOT EXISTS;
  CREATE TYPE userProfile::Profile {
      CREATE REQUIRED LINK user: accessControl::User;
      CREATE REQUIRED PROPERTY country: std::str;
      CREATE REQUIRED PROPERTY kyc_passed: std::bool {
          SET default := false;
      };
  };
  CREATE TYPE userProfile::WatchList {
      CREATE REQUIRED LINK user: accessControl::User;
  };
};
