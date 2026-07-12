# Retired project GitHub capability secrets

Project GitHub authority comes from a verified repository binding and the
GitHub App installation behind it. Local user operations use the machine's
GitHub App user authorization, while hosted automation mints short-lived
installation tokens. A project capability therefore has no long-lived GitHub
secret field.

Older installations may still contain `capability_secrets` rows whose trimmed,
case-insensitive type is `github`. Current authentication does not consume
those rows. Generic capability reads and writes refuse the GitHub secret type,
and project unbind removes any matching residue for that project without
touching unrelated capability secrets or the shared App installation.

The ticketless governed `retired_github_capability_secrets` migration removes
existing rows across the authoritative database. It takes a write-blocking
table lock, deletes only the exact normalized GitHub type, verifies no target
rows remain, and checks that the unrelated row count is unchanged. The
governed runner's backup is the rollback artifact for the irreversible values.
