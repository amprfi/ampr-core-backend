with
    user := assert_exists((select accessControl::User filter .id = <uuid>$user_id))
select (
    insert messaging::Chat {
        owner := user
    }
) {
    id
}