select (
    insert messaging::Chat {
        owner := (select accessControl::User filter .id = <uuid>$user_id)
    }
) {
    id,
    created_at,
    owner: {
        id,
        email
    }
};