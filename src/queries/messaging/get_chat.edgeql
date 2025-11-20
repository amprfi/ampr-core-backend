with
    user := (select accessControl::User filter .id = <uuid>$user_id),
    chat := (select user.<owner[is messaging::Chat] filter .id = <uuid>$chat_id)
select assert_exists(chat) {
    id,
    recent_messages: {
        id,
        role,
        channel,
        content,
        created_at,
        status
    } order by .created_at asc,
    summaries: {
        content,
        range_start,
        range_end
    } order by .range_start asc
}