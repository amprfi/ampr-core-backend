CREATE MIGRATION m1pqjifga6ef56xnt3b7ujy4jqv4m36rkqz6ll3gvulspufawagfhq
    ONTO m12xmrcrwr5y3f6wtzniukwet7kv3bxsbjeuylt52pcfbgn47swi3a
{
  ALTER TYPE default::User {
      DROP LINK identity;
      DROP PROPERTY updated_at;
  };
};
