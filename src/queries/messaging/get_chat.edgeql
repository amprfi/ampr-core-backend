with
    user := (select accessControl::User filter .id = <uuid>$user_id),
    chat := (select user.<owner[is messaging::Chat] filter .id = <uuid>$chat_id)
select assert_exists(chat) {
    id,
    # We'll add message retrieval later
}