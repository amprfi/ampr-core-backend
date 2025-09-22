CREATE MIGRATION m1fcwhnkzrpreolfxv2czp2fr7vkhilwb5bnw7ox4q5k3p34lyjwsa
    ONTO m125uc4smqoxtvuwyl65kxresw3wv33kd5xsb3aotpdq35jfve2sia
{
  ALTER TYPE accessControl::User {
      ALTER LINK identity {
          SET REQUIRED USING (<ext::auth::Identity>{});
      };
  };
};
