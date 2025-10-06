select messaging::Chat {
    id
}
filter .owner.id = <uuid>$user_id