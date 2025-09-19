with user := (select accessControl::User filter .id = <uuid>$user_id)
select user.<owner[is messaging::Chat] {
    id,
    created_at,
    message_count := count(.archive),
    recent_message_count := count(.recent_messages),
    recent_messages := (
        select .recent_messages {
            content,
            role,
            created_at
        }
        order by .created_at desc
    )
}
order by .created_at desc;