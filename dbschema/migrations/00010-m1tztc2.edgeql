CREATE MIGRATION m1tztc2g3qijueke37zbytavv7foblky5a7hpdblknz6suaptl64tq
    ONTO m15ckj3hx4egdixakwmogr7v4mc3c3mwzg7dfqpms4oj2h3w3tpsrq
{
  ALTER TYPE messaging::Message {
      DROP ACCESS POLICY owner_only;
  };
};
