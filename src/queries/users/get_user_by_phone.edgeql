select accessControl::User {
    id,
    first_name,
    last_name, 
    email,
    phone,
    country
    }
filter accessControl::User.phone = <str>$phone