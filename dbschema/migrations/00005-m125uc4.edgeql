CREATE MIGRATION m125uc4smqoxtvuwyl65kxresw3wv33kd5xsb3aotpdq35jfve2sia
    ONTO m1lkhaal747d5pzvmgsfmfwermjr56r36mb2nqxu4jcz463uqywi7a
{
  CREATE MODULE accessControl IF NOT EXISTS;
  CREATE MODULE messaging IF NOT EXISTS;
  CREATE GLOBAL accessControl::current_user -> std::uuid;
  ALTER TYPE default::User RENAME TO accessControl::User;
  CREATE TYPE messaging::Chat {
      CREATE REQUIRED LINK owner: accessControl::User;
      CREATE ACCESS POLICY owner_only
          ALLOW ALL USING ((GLOBAL accessControl::current_user ?= .owner.id));
      CREATE REQUIRED PROPERTY created_at: std::datetime {
          SET default := (std::datetime_current());
      };
  };
  CREATE TYPE messaging::Message {
      CREATE REQUIRED LINK chat: messaging::Chat;
      CREATE PROPERTY is_archived: std::bool {
          SET default := false;
      };
      CREATE ACCESS POLICY owner_only
          ALLOW ALL USING ((GLOBAL accessControl::current_user ?= .chat.owner.id));
      CREATE REQUIRED PROPERTY content: std::str;
      CREATE PROPERTY created_at: std::datetime {
          SET default := (std::datetime_current());
      };
      CREATE REQUIRED PROPERTY role: std::str;
  };
  ALTER TYPE messaging::Chat {
      CREATE MULTI LINK archive: messaging::Message;
      CREATE MULTI LINK historical_messages := (SELECT
          .archive
      FILTER
          .is_archived
      );
      CREATE MULTI LINK recent_messages := (SELECT
          .archive
      FILTER
          NOT (.is_archived)
      );
  };
};
