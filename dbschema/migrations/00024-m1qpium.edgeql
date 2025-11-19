CREATE MIGRATION m1qpiumo4tziatoc22xadipandkewfsondz6ad7mlka42hol26gysa
    ONTO m1juuapt4uhhzfoclhapnb7jxdc2t2tmoi6nbg6lu4si67n7qwnknq
{
  CREATE SCALAR TYPE messaging::MessageStatus EXTENDING enum<Current, PendingSummary, Archived>;
  ALTER TYPE messaging::Message {
      CREATE REQUIRED PROPERTY status: messaging::MessageStatus {
          SET default := (messaging::MessageStatus.Current);
      };
  };
  ALTER TYPE messaging::Chat {
      ALTER LINK archived_messages {
          USING (SELECT
              .messages
          FILTER
              (.status = messaging::MessageStatus.Archived)
          ORDER BY
              .created_at DESC
          );
      };
      CREATE MULTI LINK pending_messages := (SELECT
          .messages
      FILTER
          (.status = messaging::MessageStatus.PendingSummary)
      ORDER BY
          .created_at DESC
      );
      ALTER LINK recent_messages {
          USING (SELECT
              .messages
          FILTER
              (.status = messaging::MessageStatus.Current)
          ORDER BY
              .created_at DESC
          );
      };
  };
  CREATE TYPE messaging::Summary {
      CREATE REQUIRED LINK chat: messaging::Chat;
      CREATE PROPERTY created_at: std::datetime {
          SET default := (std::datetime_current());
      };
      CREATE INDEX ON ((.chat, .created_at));
      CREATE REQUIRED PROPERTY content: std::str;
      CREATE REQUIRED PROPERTY range_end: std::datetime;
      CREATE REQUIRED PROPERTY range_start: std::datetime;
  };
  ALTER TYPE messaging::Chat {
      CREATE MULTI LINK summaries := (.<chat[IS messaging::Summary]);
  };
  ALTER TYPE messaging::Message {
      DROP PROPERTY is_archived;
  };
};
