CREATE MIGRATION m1p7z2bvx2k75izchyjo3sauatppmnmjgmbixzcvzeuq4lqiv2wvmq
    ONTO m17awyw3cdxkre6hmplw2kwtuwhb4g63gft7n6nfbq2e7qmpnys4va
{
  ALTER TYPE messaging::Message {
      ALTER PROPERTY is_archived {
          USING (WITH
              recent_ids := 
                  ((SELECT
                      messaging::Message FILTER
                          (.chat = messaging::Message.chat)
                      ORDER BY
                          .created_at ASC
                  LIMIT
                      4
                  )).id
          SELECT
              NOT ((messaging::Message.id IN recent_ids))
          );
      };
  };
};
