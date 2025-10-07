CREATE MIGRATION m17ynb3t5pkbt3vkvbyejtrmrnwxuusir6jpiio54ydaoq7icpddfq
    ONTO m1vg6ysrt4675tvhiaxmhdyz3dqco2zsxg7uethsl5tqip5lrqn7bq
{
  ALTER TYPE messaging::Chat {
      DROP LINK historical_messages;
  };
  ALTER TYPE messaging::Chat {
      CREATE MULTI LINK messages := (.<chat[IS messaging::Message]);
  };
  ALTER TYPE messaging::Message {
      ALTER PROPERTY is_archived {
          RESET default;
          USING (WITH
              chat_recent_messages := 
                  (SELECT
                      messaging::Message {
                          id
                      } FILTER
                          (.chat = .chat)
                      ORDER BY
                          .created_at DESC
                  LIMIT
                      4
                  )
          SELECT
              (.id NOT IN chat_recent_messages.id)
          );
      };
      CREATE INDEX ON ((.chat, .created_at));
  };
  ALTER TYPE messaging::Chat {
      ALTER LINK recent_messages {
          USING (SELECT
              .messages
          FILTER
              NOT (.is_archived)
          ORDER BY
              .created_at DESC
          );
      };
  };
  ALTER TYPE messaging::Chat {
      DROP LINK archive;
  };
  ALTER TYPE messaging::Chat {
      CREATE MULTI LINK archived_messages := (SELECT
          .messages
      FILTER
          .is_archived
      ORDER BY
          .created_at DESC
      );
  };
};
