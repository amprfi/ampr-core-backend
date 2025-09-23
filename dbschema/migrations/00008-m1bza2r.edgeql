CREATE MIGRATION m1bza2rer2tujortken27rfun7hnjmv7iwerr5hycxilow3yiaqftq
    ONTO m1oakpoa2ec7ykzzxfy5rtsbetwadipwavtofgsogl33il75x7eama
{
  ALTER TYPE messaging::Chat {
      CREATE ACCESS POLICY owner_only
          ALLOW ALL USING ((GLOBAL accessControl::current_user ?= .owner.id));
  };
};
