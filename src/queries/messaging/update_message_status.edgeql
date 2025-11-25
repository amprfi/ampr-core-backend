with
  chat_id := <uuid>$chat_id,
  # Find the 25th most recent message to establish the cutoff
  cutoff_message := (
    select messaging::Message
    filter .chat.id = chat_id and .status = messaging::MessageStatus.Current
    order by .created_at desc
    offset 19 limit 1
  )
# Update messages older than the cutoff to PendingSummary
select (
  update messaging::Message
  filter
    .chat.id = chat_id
    and .status = messaging::MessageStatus.Current
    and .created_at < cutoff_message.created_at
  set {
    status := messaging::MessageStatus.PendingSummary
  }
) { id };

# Return the total count of PendingSummary messages for this chat
select count(
  messaging::Message
  filter .chat.id = <uuid>$chat_id and .status = messaging::MessageStatus.PendingSummary
)
