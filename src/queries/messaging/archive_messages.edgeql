with 
    cutoff_message := (
        select messaging::Message
        filter .chat.id = <uuid>$chat_id and not .is_archived
        order by .created_at desc
        offset 29 limit 1  # 30th most recent message
    )
update messaging::Message
filter (
    .chat.id = <uuid>$chat_id and
    not .is_archived and
    .created_at < cutoff_message.created_at
)
set {
    is_archived := true
};