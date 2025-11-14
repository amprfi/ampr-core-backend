INSERT userProfile::Profile {
    user := (SELECT accessControl::User FILTER .id = <uuid>$userid),
    country := <str>$country,
    kyc_passed := <bool>$kyc_passed
};