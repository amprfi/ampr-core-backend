with
  chat_id := <uuid>$chat_id,
  summary_content := <str>$content,
  range_start := <datetime>$range_start,
  range_end := <datetime>$range_end,
  message_ids := <array<uuid>>$message_ids

select {
  summary := (
    insert messaging::Summary {
      chat := (select messaging::Chat filter .id = chat_id),
      content := summary_content,
      range_start := range_start,
      range_end := range_end
    }
  ),
  archived_messages := (
    update messaging::Message
    filter .id in array_unpack(message_ids)
    set {
      status := messaging::MessageStatus.Archived
    }
  )
}
