CREATE MIGRATION m17awyw3cdxkre6hmplw2kwtuwhb4g63gft7n6nfbq2e7qmpnys4va
    ONTO m1w26p6ocfjibvhmf74wslwplu4ksknfda46pd4gidjxkevj2rdsza
{
  ALTER TYPE messaging::Message {
      ALTER PROPERTY is_archived {
          USING (WITH
              recent_ids := 
                  ((SELECT
                      messaging::Message FILTER
                          (.chat = messaging::Message.chat)
                      ORDER BY
                          .created_at DESC
                  LIMIT
                      4
                  )).id
          SELECT
              NOT ((messaging::Message.id IN recent_ids))
          );
      };
  };
};
