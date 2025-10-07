CREATE MIGRATION m1xinge7ghdu6kiaghqzgujd27u6ifwyduftnql6miojjuku4ihtla
    ONTO m1gbmp5gvqpw46at5geexh7ycl7fyjr26edmdurgf5u5m2yhrvd7pq
{
  ALTER TYPE messaging::Message {
      ALTER PROPERTY is_archived {
          USING (true);
      };
  };
};
