CREATE MIGRATION m1luw2a2ngfqxd5fqpcd36upkysxkwkcj3u4wxj4vrtzap6flzitja
    ONTO m1kluo2lmg244mjqokwusrnnk34zh7a2xlrmbcxqbgswkxqjcku7pa
{
  ALTER TYPE accessControl::User {
      DROP PROPERTY country;
  };
};
