# Machine authorization

Cloud and self-hosted servers share the device-code wire contract in
`yoke_contracts.machine_authorization`. Cloud retains its start/poll wire and
org selection. Self-host binds a code to its sole organization at start.

## Connect

Run `yoke connect https://<server>` and approve your own machine in the signed-in
workbench. The setup wizard's **A team server** option discovers the server's
sign-in method before showing browser approval or API-token entry. Without
company sign-in, use `yoke connect https://<server> --token-stdin` or
`--token-file PATH`. The first-boot admin token remains the bootstrap.

## Wire

- `POST /api/machine/authorizations` returns `device_code`, `user_code`,
  `verification_uri`, `verification_uri_complete`, `expires_in`, and `interval`.
  Cloud's start body stays empty. Self-host sends `machine_id` and `machine_name`
  so the approval page identifies the machine before its first poll.
- `POST /api/machine/authorizations/token` sends `device_code`, `machine_id`, and
  `machine_name`. Success returns `token`, `org`, and `api_url`.
- Retry HTTP 202 `authorization_pending`, HTTP 503
  `machine_credential_unavailable`, and HTTP 429
  `authorization_poll_rate_limited` (honoring `Retry-After`). HTTP 410
  `authorization_denied`, `authorization_expired`, or `authorization_consumed`
  requires a new connection. Other statuses are diagnosed refusals.
- Cloud's API authority is `/api/orgs/<slug>` on the selected origin. Self-host's
  authority is the server origin. Clients reject foreign origins or mismatched
  authorities before persisting a credential.
- Self-host discovery is `GET /api/machine/authorizations`: `device_code` is true
  exactly when company sign-in is configured. Partial configuration refuses as
  `oidc_misconfigured`; an older server without discovery requires an explicit
  API token until its operator upgrades it. The wizard retains the discovery
  refusal and offers **Use API token**, **Edit connection**, and **Choose another
  home**, including when company sign-in is misconfigured.

## Approval and delivery

The shared `/machine-approval[/CODE]` workbench page calls
`machine_authorization.get` and `machine_authorization.resolve` through its
normal function client. The read returns `authorization` with code, machine
name/ID, expiry, and decision; resolve takes `{code, action: approve|deny}`
and returns that decision. A host consuming the core wheel supplies its normal
client and owns its pending-code store; Cloud's companion integration maps
these calls to its store, where organization selection occurs at approval.

Self-host accepts decisions only from active org members. The signed-in person
claims the code and approves their own machine through a named-actor decision
request; other actors cannot take it over. Cloud's existing org-admin requests
retain their role authority. Credential issuance remains engine-owned atomic
machine registration/rotation. Consumption and issuance commit together; one
poll receives the raw credential and no raw credential is stored in the code
record. Network loss after delivery requires starting a new code.

The self-host store keeps hashed device secrets and expires codes after ten
minutes, deleting expired records on the next start. Pending admission is bounded
by trusted transport client identity: eight unconsumed codes per client and
128 across the server. Changing the machine UUID or forwarding headers does
not create a new client budget. `authorization_client_capacity` and
`authorization_capacity` refuse further starts; finish an approval or retry
after expiry. Consumed codes free pending capacity.

Persistent atomic counters are shared across processes and restarts, separately
from telemetry: six start requests and 120 poll requests per client per minute.
HTTP 429 `authorization_start_rate_limited` or `authorization_poll_rate_limited`
includes `Retry-After`. Start refusals require retrying after that delay. The CLI
waits through poll throttling and polls the same code after `Retry-After`, bounded
by its expiry and cancellation. Missing or invalid delays retain the normal poll
interval; capacity refusals remain fatal. Failed and malformed
requests also consume the budget. For self-host, set `YOKE_API_TRUSTED_PROXIES`
in the bundle's `.env` to the TLS proxy IPs/CIDRs, then restart with
`yoke self-host init --dir PATH --protect-existing --start` so the server sees
each forwarded client. Headers from undeclared peers are ignored; clients
sharing an address share these budgets. A denied, consumed,
or expired code requires a new connection. Wrong machine identity, missing
org membership, or disabled actor refuses with its recovery step. A database
failure before issuance leaves delivery retryable. Cookies authorize browser
functions only with the workbench's existing same-origin CSRF protection.

## Inspect as the signed-in actor

Run `yoke machine-authorization get CODE` to read a code, then
`yoke machine-authorization resolve CODE --action approve` (or `deny`) to
record your personal decision. Read the returned decision and finish polling
from the original machine. These operations never accept a caller-supplied
owner, org, or credential.

## Shared schema

The `yoke-contracts` wheel ships `yoke_contracts/machine_authorization.schema.v1.json`,
generated from the request and response Pydantic models. Load it with Python's
`importlib.resources.files("yoke_contracts").joinpath("machine_authorization.schema.v1.json")`,
or read that path from the pinned wheel in another language. Validate a body
against its named `$defs` entry while retaining the document's other `$defs`
for references. The `x-http` section names the endpoint, request model, success
model, error outcome's HTTP status and body model, and retry policy. Cloud's
empty start request is explicitly host-specific; poll requests are shared.

`MachineAuthorizationStarted` and `MachineAuthorizationApproved` define success.
`MachineAuthorizationPending`, `MachineAuthorizationDenied`,
`MachineAuthorizationExpired` (including consumed), `MachineAuthorizationSlowDown`,
and `MachineAuthorizationUnavailable` define poll outcomes. Other diagnosed
refusals use `MachineAuthorizationRefused`. Recovery `message` is optional
on the wire; self-host supplies it. Secrets are excluded from model repr and
client validation errors. The CLI and self-host route use these models;
`parse_authorization_response` also checks known poll statuses. Origin and API
authority checks remain required after body validation.

Regenerate after changing models with
`yoke dev run -- python3 -m yoke_contracts.machine_authorization_schema`.
Check drift with the same command plus `--check`; the contract test also fails
on byte drift. A breaking wire change requires a new schema version and the
linked consumer's tests against the exact candidate wheel. The schema's v1
identifies its contract independently of the wheel's release version.

Shared client helpers are `authorization_origin`, `same_origin_url`,
`credential_api_url`, and `parse_authorization_response`, with
`BROWSER_VERIFICATION_PATHS`, `POLL_OUTCOMES`, and `RETRYABLE_POLL_ERRORS`.
