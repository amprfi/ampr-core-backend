select accessControl::User {
  id
}
filter .identity = global ext::auth::ClientTokenIdentity