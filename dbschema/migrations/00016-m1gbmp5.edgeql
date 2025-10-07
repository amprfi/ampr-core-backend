CREATE MIGRATION m1gbmp5gvqpw46at5geexh7ycl7fyjr26edmdurgf5u5m2yhrvd7pq
    ONTO m1p7z2bvx2k75izchyjo3sauatppmnmjgmbixzcvzeuq4lqiv2wvmq
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
