select accessControl::User {first_name, last_name, email}
filter accessControl::User.email = <str>$email