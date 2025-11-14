select accessControl::User {
    id,
    first_name,
    last_name, 
    email,
    phone
    }
filter accessControl::User.phone = <str>$phone