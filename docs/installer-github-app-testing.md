# Installer GitHub App Live Testing

This companion to [Installer Testing](INSTALLER-TESTING.md) defines the live
GitHub App execution boundary and owns the canonical append-only Wave 5 table.
The campaign loader composes these rows with the main guide for manifests and
assignments, then rejects duplicate ids across both documents.

### Wave 5: Machine GitHub App Connection

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `GITHUB-001` | `prepared-yoke` | Skip GitHub | Project step reachable; machine config has no GitHub App connection |
| `GITHUB-002` | `prepared-yoke` | Connect GitHub App | Device page opens; one-time code renders; no credential paste field appears |
| `GITHUB-003` | `fault-injection` | Device authorization pending then succeeds | Poll interval is honored; identity, installations, and repositories refresh before Project |
| `GITHUB-004` | `prepared-yoke` | Device authorization expires or is denied | Friendly retry/backlog-only guidance; no partial machine credential is written |
| `GITHUB-005` | `prepared-stored-state` | Stored App authorization | Live refresh succeeds; identity and installation summary render; no credential value leaks |
| `GITHUB-006` | `prepared-stored-state` | Revoked App authorization | Friendly reconnect guidance; no crash; stale cached access is not accepted |
| `GITHUB-007` | `prepared-yoke` | App sees many repos | Repository list truncates consistently and does not overflow |
| `GITHUB-008` | `prepared-yoke` | Default App grant lacks Administration | New-repo/environment/runner mutations are skipped with a GitHub settings link |
| `GITHUB-009` | `prepared-stored-state` | Stored App authorization reuse | Refresh is serialized and verified, not blindly trusted |
| `GITHUB-010` | `fault-injection` | Concurrent refresh-token use | Callers serialize; the second request submits the first request's rotated refresh credential; both callers receive usable access tokens and the final rotation is stored atomically |
| `GITHUB-011` | `prepared-yoke` | Select local, hosted, and team-server destinations | Each destination resolves its own public App metadata; client id, slug, and GitHub origin never bleed across destinations |
| `GITHUB-012` | `prepared-yoke` | User authorization succeeds before App installation | Pending-install screen remains on GitHub; Check access refreshes live state and advances only after a usable installation is visible |
| `GITHUB-013` | `prepared-yoke` | Choose Back from a GitHub connection error | Returns to Connect GitHub / Use backlog only without launching another browser or worker |
| `GITHUB-014` | `fault-injection` | Destination metadata and stored App identity disagree | Connection is refused with reconnect guidance; cached repositories from the other App are not accepted |
| `GITHUB-015` | `prepared-stored-state` | Disconnect then reconnect machine GitHub authorization | Local credential and config reference are removed, App installation/project bindings remain, and reconnect writes one fresh credential |
| `GITHUB-016` | `prepared-git` | Bind an App-visible repository to a project | Verified installation/repository ids and repo binding persist; explicit issue-sync policy is preserved |
| `GITHUB-017` | `prepared-git` | Create, update, comment, label, close, and reopen an issue | Every mutation succeeds through resolved App auth; validation failures are nonzero and never reported as repo mismatch without evidence |
| `GITHUB-018` | `prepared-git` | Create a pull request for the bound project | PR targets the verified bound repo and succeeds through short-lived App auth |
| `GITHUB-019` | `prepared-git` | Read and mutate GitHub Actions state | Workflow, run, variable, and secret operations target the verified bound repo and use short-lived App auth |
| `GITHUB-020` | `prepared-yoke` | Team server publishes a complete GitHub App public profile | Engineer-machine connect uses that server's client id, slug, and origins; authorization, install, repo discovery, and binding complete |
| `GITHUB-021` | `fault-injection` | Team server has no or partial GitHub App public profile | Wizard explains the operator-owned missing fields and offers backlog-only; no official-hosted or cached App fallback is used |
| `GITHUB-022` | `fault-injection` | Bind repository metadata discovered through a different App | Server rejects the foreign App/installation identity and preserves the prior binding and sync policy |
| `GITHUB-023` | `prepared-stored-state` | Inspect disk after connect and refresh | Owner-only storage contains only the refresh credential; access tokens remain process-memory/transient and secret scans stay green |
| `GITHUB-024` | `prepared-stored-state` | Revoked saved authorization with backlog-only and a public clone | Backlog-only/public clone completes without refreshing GitHub authorization; connected-repo/private operations still require reconnect |
| `GITHUB-025` | `prepared-stored-state` | Retry, Check access, and Back repeatedly across pending and error screens | Screen history stays bounded; Back returns to the prior choice without relaunching a browser or worker; a successful retry advances once |
| `GITHUB-026` | `prepared-stored-state` | Refresh project repo access, use Back, and repeat without a machine connection | Refresh replaces its progress screen instead of growing history; Back returns to project choices; no-machine state offers backlog-only with no App-binding dead end |
| `GITHUB-027` | `fault-injection` | Reconnect from a working authorization, then fail discovery for the replacement or a different App profile | Existing config, refresh credential, and helper remain usable until replacement verification completes; failure rolls back without deleting or cross-wiring either profile; success swaps atomically |
| `GITHUB-028` | `prepared-git` | Clone a public repo, then a private repo with connected machine authorization | Public clone attempts anonymous access first and performs no refresh; an access-shaped private failure acquires one transient token and retries without persisting it in Git config |
| `GITHUB-029` | `prepared-stored-state` | Disconnect with registered checkouts spanning service origins and user/global helper chains | Machine config and owned refresh credential are removed; only Yoke-owned URL-scoped helpers are removed from every registered checkout; ambient and user helpers survive; cleanup findings are aggregated |
| `GITHUB-030` | `prepared-stored-state` | Connect with an installed older Yoke credential helper schema | Stable helper code is republished atomically before the new refresh-only credential is committed; an upgrade failure preserves prior config and credential state |
| `GITHUB-031` | `fault-injection` | Return oversized, invalid-UTF-8, and secret-echoing OAuth/API/publish responses | Per-response limits and decoding checks fail closed with typed, generic guidance; no secret-shaped body or transport reason reaches screens/reports; prior authoritative state is preserved |
| `GITHUB-032` | `fault-injection` | Start a self-hosted server with complete private App credentials but no public profile | Startup attests the private App identity and stays available; health reports public GitHub connection unavailable without leaking private metadata; binding still enforces the attested App |
| `GITHUB-033` | `prepared-yoke` | Compare fresh local default, explicit local App profile, and a service-published product profile | Missing baseline product App is an explicit setup blocker with no development-App fallback; a complete local override works only for local mode; a complete published product profile drives the normal flow |
| `GITHUB-034` | `fault-injection` | Select an HTTPS service while conflicting App metadata is present in environment variables, then select local with an explicit profile | HTTPS connect and binding use the selected service's credential-free health profile and ignore ambient App metadata; local explicit mode performs no hosted profile fetch |
| `GITHUB-035` | `fault-injection` | Chain rotations across two serialized local GitHub operations | Refresh requests never overlap; operation two submits operation one's rotated credential; the final owner-only file contains only the last refresh credential and no access token is written |
| `GITHUB-036` | `prepared-yoke` | Connect successfully, then choose Back, backlog-only, or quit before project Apply | Every exit truthfully says machine authorization was saved immediately and names `yoke github disconnect`; no project binding is claimed; the saved connection remains reusable or can be explicitly removed |
| `GITHUB-037` | `fault-injection` | Traverse adversarial pagination and retry responses until the aggregate operation budget is exhausted | One total deadline plus request, row, and byte budgets bound the full operation; traversal stops with generic repair guidance; no partial discovery or binding snapshot becomes authoritative |
| `GITHUB-038` | `fault-injection` | Boot the native self-host container from owner-only host DSN, OIDC, and App-key sources | The final UID 100 process reads copied runtime credentials; host sources remain mode 0600 and root-owned; no secret content or broadened permission is retained |
| `GITHUB-039` | `fault-injection` | Delay startup App identity with slow DNS and slow-trickle responses beyond the aggregate deadline | The hard startup deadline ends attestation; the API becomes ready with GitHub advertisement disabled; health and logs remain bounded and secret-free |
| `GITHUB-040` | `fault-injection` | Return oversized, invalid-UTF-8, and secret-echoing generic REST and installation-token responses | Response and decode limits fail closed; errors are generic and redacted; no partial token, binding, or discovery state becomes authoritative |
| `GITHUB-041` | `fault-injection` | Serve oversized and adversarial GitHub Actions log archives | Archive byte, entry-count, per-entry, compression-ratio, and aggregate extraction limits reject ZIP bombs safely without returning partial logs or writing outside scratch space |
| `GITHUB-042` | `prepared-stored-state` | Upgrade Yoke or Python with an older Yoke-owned repo credential helper still configured | Reconnect safely recognizes and replaces the older owned helper, authenticated Git operations work, and disconnect removes it without treating foreign lookalikes as owned |
| `GITHUB-043` | `fault-injection` | Point clone resume and Start over at pre-existing, nested, home, symlink, dangling-symlink, and concurrently replaced paths | Resume requires the exact repository top level; Start over and failed-clone cleanup remove only output proven to belong to this run; every unrelated or replaced path survives unchanged |
| `GITHUB-044` | `prepared-stored-state` | Connect, use Back, choose backlog-only, and reselect different project modes and repositories | Run-scoped GitHub and project fields reset together; no private lookup, publish, stale existing-project mapping, or App binding leaks from the abandoned path |
| `GITHUB-045` | `prepared-stored-state` | Select an organization or private repository beyond the first bounded API page | Bounded pagination or an authenticated paste/search fallback keeps the target reachable, preserves private-auth intent, and verifies the selected owner and clone URL as one identity |
| `GITHUB-046` | `fault-injection` | Fail credential deletion during disconnect, replacement cleanup, and config-write rollback, then repair permissions and retry | The exact orphan remains durably cleanup-pending, the authoritative connection is preserved or cleared as reported, and a later retry removes only the recorded orphan |
| `GITHUB-047` | `prepared-git` | Resume make-it-mine and fork after an ambiguous response or partial local remote change | Yoke re-reads the expected repository, owner, parent, fork marker, and privacy from GitHub before pushing; a different or merely source-related origin is rejected without mutation |
| `GITHUB-048` | `fault-injection` | Press Ctrl-C during Connect, Check access, owner/repo loading, private-clone authorization, and every other refresh-backed checking screen | Quit is deferred until the refresh-token exchange and owner-only save commit or roll back; no worker writes after UI exit; the prior or rotated credential remains usable and no access token reaches evidence |
| `GITHUB-049` | `prepared-git` | With the baseline no-Administration App, choose publish or Duplicate, create an empty repo in GitHub, grant App access, return to Check access, and explicitly select the live repo | One-step create/fork rows remain unavailable; no same-name inference or silent clone downgrade occurs; the exact selected empty repo and compatible origin are reverified, push succeeds or rolls back safely, and sync enables only after an active binding |
| `GITHUB-050` | `prepared-git` | Finish ordinary private clone, existing-checkout, and publish flows, then run Git after the wizard and after a Yoke upgrade | The clean HTTPS remote has an exact Yoke-owned URL-scoped helper; plain fetch/pull and push dry-run authenticate without reconnecting; no access token is stored in the remote, Git config, report, or helper bundle |
| `GITHUB-051` | `prepared-stored-state` | Re-onboard an existing checkout with a GitHub origin against both an active-bound project and an existing backlog-only project | Detected repo/remote identity survives the existing-remote path; active binding and sync are preserved without a false backlog-only report; the unbound project offers an explicit verified bind-or-preserve choice and a requested bind is not skipped merely because the project or remote already exists |
| `GITHUB-052` | `fault-injection` | Use two supported config paths sharing one machine secret root; interrupt connect/replacement/disconnect at credential write, config CAS, quarantine, and restore boundaries | One config never deletes or quarantines the other's live or recovery credential; each pending transaction has exact config ownership; crash recovery removes only proven orphans and leaves no unreferenced long-lived refresh credential |

Only `GITHUB-001` and `PUBLISH-001` currently have deterministic coordinator
recipes. `GITHUB-002` through `GITHUB-052`, `PUBLISH-002` through `PUBLISH-013`,
`PROJECT-SOURCE-006`, `PROJECT-META-008`, `APPLY-005`, `APPLY-008`, `STATE-002`,
and `STATE-007` require an operator-attended run against a real GitHub App. A
blocked recipe stub is not a pass and must not be reported as automated proof.
Retain terminal captures, browser screenshots where allowed, post-apply state,
and a secret scan for every manual result.

## Evidence boundary

- `GITHUB-001` proves only the backlog-only branch. It says nothing about
  browser authorization, App installation, or repository automation.
- `GITHUB-002` through `GITHUB-016`, plus `GITHUB-020` through `GITHUB-052`,
  require both screen evidence and post-apply
  machine/control-plane state. A green screen without the expected credential,
  installation, or binding state is a failure.
- `GITHUB-017` through `GITHUB-019` require an observed successful GitHub API
  outcome in addition to Yoke state. A mocked bearer transport or a skipped
  mutation is not live proof.
- Disconnect evidence must distinguish local user authorization from the
  GitHub-managed App installation and project repo binding; they are separate
  layers with separate removal operations.
- `GITHUB-025`, `GITHUB-026`, and `GITHUB-036` require an ordered capture for
  every navigation transition. A final screen alone cannot prove bounded
  history, absence of an implicit reconnect, or truthful immediate-save copy.
- `GITHUB-027` through `GITHUB-030`, `GITHUB-034`, and `GITHUB-035` require
  before/after machine state plus redacted transport/helper traces. Preserve a
  known-good connection long enough to prove rollback and helper ownership;
  never retain access-token or device-code values as evidence.
- `GITHUB-031`, `GITHUB-032`, and `GITHUB-037` require controlled hostile or
  self-host fixtures and bounded server/client logs. Unit fault injection may
  supplement the campaign, but it does not turn a blocked coordinator stub into
  live proof.
- `GITHUB-038` and `GITHUB-039` require native-container startup evidence that
  includes final-process identity, redacted source/runtime file metadata, hard
  deadline timing, readiness, and health advertisement state.
- `GITHUB-040` and `GITHUB-041` require hostile transport/archive fixtures plus
  bounded response and scratch-tree evidence. A generic error without proof of
  every aggregate limit is incomplete.
- `GITHUB-042` through `GITHUB-052` require before/after filesystem, wizard,
  GitHub API, and Git-configuration evidence appropriate to the row. A mocked
  happy path does not prove upgrade ownership, deletion provenance, abandoned-
  path state reset, beyond-first-page reachability, cleanup retry, or live
  resume identity.
