CREATE MIGRATION m1cy2dbvjuhi7qri4rjyxi2doew2l3a56ek65ixhcdxwgkw4w3iwwq
    ONTO m1udombecmmaurmsvk7l7cug4j2x37nlml5xz2cqq5eu4zfb2sml4q
{
  ALTER TYPE accessControl::User {
      DROP LINK identity;
  };
  DROP EXTENSION auth;
  DROP EXTENSION pgcrypto;
};
