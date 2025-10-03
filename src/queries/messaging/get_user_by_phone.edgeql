select accessControl::User {id, first_name, last_name, phone}
filter accessControl::User.phone = <str>$phone_number