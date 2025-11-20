CREATE MIGRATION m1owdgi27dg566y3tk3xomuaa2bh4h3njszzae26rjqbxvpeuh4e3a
    ONTO m1qpiumo4tziatoc22xadipandkewfsondz6ad7mlka42hol26gysa
{
  ALTER TYPE messaging::Chat {
      ALTER LINK archived_messages {
          USING (SELECT
              .messages
          FILTER
              (.status = messaging::MessageStatus.Archived)
          );
      };
      ALTER LINK pending_messages {
          USING (SELECT
              .messages
          FILTER
              (.status = messaging::MessageStatus.PendingSummary)
          );
      };
      ALTER LINK recent_messages {
          USING (SELECT
              .messages
          FILTER
              (.status = messaging::MessageStatus.Current)
          );
      };
  };
};
