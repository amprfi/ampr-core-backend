select (
    insert User {
        first_name := <str>$first_name,
        last_name := <str>$last_name,
        email := <str>$email,
        phone := <str>$phone,
        country := <str>$country
    }
) {
    first_name,
    last_name,
    email,
    phone,
    country,
    created_at
};