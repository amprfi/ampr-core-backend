CREATE MIGRATION m1lkhaal747d5pzvmgsfmfwermjr56r36mb2nqxu4jcz463uqywi7a
    ONTO m1eckb5zmm77qdk25fa5bft2xzalbf34cxjqjkdwhahs5twczoauza
{
  ALTER TYPE default::User {
      CREATE LINK identity: ext::auth::Identity {
          CREATE CONSTRAINT std::exclusive;
      };
  };
};
