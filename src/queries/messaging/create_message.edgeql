with
    user := (select accessControl::User filter .id = <uuid>$user_id),
    chat := (select assert_exists(user.<owner[is messaging::Chat] filter .id = <uuid>$chat_id))
insert messaging::Message {
    chat := chat,
    role := <str>$role,
    channel := <str>$channel,
    content := <str>$content,
    created_at := datetime_current(),
    is_archived := false,
}