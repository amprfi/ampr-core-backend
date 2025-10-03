select messaging::Chat {
    id
}
filter .owner.phone = <str>$phone_number