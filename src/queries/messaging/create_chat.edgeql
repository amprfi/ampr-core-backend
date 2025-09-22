with
    user := (select accessControl::User filter .id = <uuid>$user_id)
insert messaging::Chat {
    owner := user,
}