select (
    insert accessControl::User {
        first_name := <str>$first_name,
        last_name := <str>$last_name,
        email := <str>$email,
        phone := <str>$phone,
    }
) {
    first_name,
    last_name,
    email,
    phone,
    created_at
};