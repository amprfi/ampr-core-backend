CREATE MIGRATION m1oakpoa2ec7ykzzxfy5rtsbetwadipwavtofgsogl33il75x7eama
    ONTO m1fcwhnkzrpreolfxv2czp2fr7vkhilwb5bnw7ox4q5k3p34lyjwsa
{
  ALTER TYPE messaging::Chat {
      DROP ACCESS POLICY owner_only;
  };
};
