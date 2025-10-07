CREATE MIGRATION m1w26p6ocfjibvhmf74wslwplu4ksknfda46pd4gidjxkevj2rdsza
    ONTO m17ynb3t5pkbt3vkvbyejtrmrnwxuusir6jpiio54ydaoq7icpddfq
{
  ALTER TYPE messaging::Message {
      ALTER PROPERTY is_archived {
          USING (WITH
              chat_recent_messages := 
                  (SELECT
                      messaging::Message {
                          id
                      } FILTER
                          (__source__.chat = .chat)
                      ORDER BY
                          .created_at DESC
                  LIMIT
                      4
                  )
          SELECT
              (__source__.id NOT IN chat_recent_messages.id)
          );
      };
  };
};
