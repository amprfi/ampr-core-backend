CREATE MIGRATION m1vg6ysrt4675tvhiaxmhdyz3dqco2zsxg7uethsl5tqip5lrqn7bq
    ONTO m1tztc2g3qijueke37zbytavv7foblky5a7hpdblknz6suaptl64tq
{
  ALTER TYPE messaging::Chat {
      DROP ACCESS POLICY owner_only;
  };
};
