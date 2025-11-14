select (
    insert accessControl::User {
        first_name := <str>$first_name,
        last_name := <str>$last_name,
        email := <str>$email,
        phone := <str>$phone,
        identity := (global ext::auth::ClientTokenIdentity)
    }
) {
    first_name,
    last_name,
    email,
    phone,
    identity,
    created_at
};