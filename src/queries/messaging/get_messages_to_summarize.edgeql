select messaging::Message {
  id,
  role,
  content,
  created_at
}
filter
  .chat.id = <uuid>$chat_id
  and .status = messaging::MessageStatus.PendingSummary
order by .created_at asc
limit 25
