select (
    insert messaging::Message {
        role := <str>$role,
        content := <str>$content,
        chat := (select messaging::Chat filter .id = <uuid>$chat_id)
    }
) {
    id,
    role,
    content,
    created_at,
    chat: {
        id
    }
};