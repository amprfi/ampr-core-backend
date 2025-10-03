CREATE MIGRATION m15ckj3hx4egdixakwmogr7v4mc3c3mwzg7dfqpms4oj2h3w3tpsrq
    ONTO m1bza2rer2tujortken27rfun7hnjmv7iwerr5hycxilow3yiaqftq
{
  ALTER TYPE messaging::Message {
      CREATE REQUIRED PROPERTY channel: std::str {
          SET REQUIRED USING (<std::str>{});
      };
  };
};
