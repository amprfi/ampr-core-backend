CREATE MIGRATION m13i2nrskufcvquxyleqvk67qblhl44mesuneqsfuoohtknsw6nj5a
    ONTO m1inyvjniaqyyhmrb2xatc5pyv7utxnbgyxs6gd5cznzfhbir54fsq
{
  ALTER TYPE messaging::Message {
      ALTER PROPERTY is_archived {
          SET default := false;
          RESET EXPRESSION;
          RESET CARDINALITY;
          SET REQUIRED;
          SET TYPE std::bool;
      };
  };
};
