select userProfile::Profile {
    country
}
filter .user.id = <uuid>$user_id
limit 1
