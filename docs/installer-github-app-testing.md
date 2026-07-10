# Installer GitHub App Live Testing

This companion to [Installer Testing](INSTALLER-TESTING.md) owns the live GitHub App scenario boundary. Only `GITHUB-001` and `PUBLISH-001` are automated. `GITHUB-002` through `GITHUB-010`, `PUBLISH-002` through `PUBLISH-013`, `PROJECT-SOURCE-006`, `PROJECT-META-008`, `APPLY-005`, `APPLY-008`, `STATE-002`, and `STATE-007` remain manual/IRL until the harness has a trusted HTTPS device-flow and App-installation fixture. The recipe seeder leaves those stubs blocked; it never substitutes a token-file fixture or counts them as ready.

## Machine GitHub App Connection

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `GITHUB-001` | `prepared-yoke` | Skip GitHub | Project step reachable; machine config has no GitHub App connection |
| `GITHUB-002` | `prepared-yoke` | Connect GitHub App | Device page opens; one-time code renders; no credential paste field appears |
| `GITHUB-003` | `fault-injection` | Device authorization pending then succeeds | Poll interval is honored; identity, installations, and repositories refresh before Project |
| `GITHUB-004` | `prepared-yoke` | Device authorization expires or is denied | Friendly retry/backlog-only guidance; no partial machine credential is written |
| `GITHUB-005` | `prepared-yoke` | Stored App authorization | Live refresh succeeds; identity and installation summary render; no credential value leaks |
| `GITHUB-006` | `prepared-yoke` | Revoked App authorization | Friendly reconnect guidance; no crash; stale cached access is not accepted |
| `GITHUB-007` | `prepared-yoke` | App sees many repos | Repository list truncates consistently and does not overflow |
| `GITHUB-008` | `prepared-yoke` | Default App grant lacks Administration | New-repo/environment/runner mutations are skipped with a GitHub settings link |
| `GITHUB-009` | `prepared-stored-state` | Stored App authorization reuse | Refresh is serialized and verified, not blindly trusted |
| `GITHUB-010` | `fault-injection` | Concurrent refresh-token use | One refresh request rotates the credential atomically; both callers receive a usable access token |
