CREATE MIGRATION m12xmrcrwr5y3f6wtzniukwet7kv3bxsbjeuylt52pcfbgn47swi3a
    ONTO initial
{
  CREATE EXTENSION pgcrypto VERSION '1.3';
  CREATE EXTENSION auth VERSION '1.0';
  CREATE FUTURE simple_scoping;
  CREATE TYPE default::User {
      CREATE REQUIRED LINK identity: ext::auth::Identity {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE REQUIRED PROPERTY country: std::str;
      CREATE REQUIRED PROPERTY created_at: std::datetime;
      CREATE REQUIRED PROPERTY email: std::str {
          CREATE CONSTRAINT std::exclusive;
          CREATE CONSTRAINT std::max_len_value(255);
          CREATE CONSTRAINT std::regexp(r'^[\w\.\-]+@([\w\-]+\.)+[\w\-]{2,}$');
      };
      CREATE REQUIRED PROPERTY first_name: std::str;
      CREATE REQUIRED PROPERTY last_name: std::str;
      CREATE REQUIRED PROPERTY phone: std::str {
          CREATE CONSTRAINT std::exclusive;
          CREATE CONSTRAINT std::max_len_value(20);
          CREATE CONSTRAINT std::regexp(r'^\+?[\d\s\-\(\)]{10,}$');
      };
      CREATE REQUIRED PROPERTY updated_at: std::datetime;
  };
};
