select (
    insert accessControl::User {
        first_name := <str>$first_name,
        last_name := <str>$last_name,
        email := <str>$email,
        phone := <str>$phone,
        country := <str>$country,
        identity := (global ext::auth::ClientTokenIdentity)
    }
) {
    first_name,
    last_name,
    email,
    phone,
    country,
    identity,
    created_at
};