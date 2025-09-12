CREATE MIGRATION m1eckb5zmm77qdk25fa5bft2xzalbf34cxjqjkdwhahs5twczoauza
    ONTO m1pqjifga6ef56xnt3b7ujy4jqv4m36rkqz6ll3gvulspufawagfhq
{
  ALTER TYPE default::User {
      ALTER PROPERTY created_at {
          SET default := (std::datetime_current());
          SET readonly := true;
      };
  };
};
