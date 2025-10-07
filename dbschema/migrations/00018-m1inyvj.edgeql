CREATE MIGRATION m1inyvjniaqyyhmrb2xatc5pyv7utxnbgyxs6gd5cznzfhbir54fsq
    ONTO m1xinge7ghdu6kiaghqzgujd27u6ifwyduftnql6miojjuku4ihtla
{
  ALTER TYPE messaging::Message {
      ALTER PROPERTY is_archived {
          USING ((.role = 'user'));
      };
  };
};
