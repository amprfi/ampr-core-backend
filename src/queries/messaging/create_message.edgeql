with
    user := (select accessControl::User filter .id = <uuid>$user_id),
    existing_chat := (select user.<owner[is messaging::Chat] limit 1),
    target_chat := existing_chat ?? (
        insert messaging::Chat {
            owner := user,
            created_at := datetime_current(),
        }
    )
insert messaging::Message {
    chat := target_chat,
    role := <str>$role,
    channel := <str>$channel,
    content := <str>$content,
    created_at := datetime_current(),
    is_archived := false,
}