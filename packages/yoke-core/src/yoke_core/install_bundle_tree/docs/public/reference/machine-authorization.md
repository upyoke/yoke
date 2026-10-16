# Machine authorization

Cloud and self-hosted servers share the device-code wire contract in
`yoke_contracts.machine_authorization`. Cloud retains its org selection. Self-host binds a code to its sole organization at start.

## Connect

Run `yoke connect https://<server>` and compare the four-character **Match code**
with your own machine's request. Approve it from a machine already connected to
that server with `yoke machines approve K7F2`, or use **Machines → Waiting for
approval** in the signed-in workbench. The setup wizard's **A team server** option discovers the server's
sign-in method before showing browser approval or API-token entry. Without
company sign-in, a first machine uses `yoke connect https://<server> --token-stdin`
or `--token-file PATH`; the first-boot admin token remains the bootstrap. Your
own next machine runs `yoke connect https://<server>` and you approve its code
from a machine you already connected with
`yoke machines approve CODE`. The approved
machine receives the approver's identity, so approve only your own codes; the
wizard therefore keeps a teammate without company sign-in on API-token entry.

## Wire

- `POST /api/machine/authorizations` returns `device_code`, `user_code`,
  `verification_uri`, `verification_uri_complete`, `expires_in`, and `interval`.
  Every mode sends `machine_id` (the configured UUID), `machine_name` (the
  operating system display hostname, at most 150 characters), and `platform`
  (for example `macOS`, `Linux` or `Windows`, at most 80 characters). All three
  are required by `MachineAuthorizationStart`; the browser reads these facts
  before the first poll. Start with the current installer against a server
  serving this request contract; a mismatched contract refuses by name.
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
- Self-host discovery is `GET /api/machine/authorizations`: `device_code` is
  true on every current server, and `company_sign_in` is true exactly when
  company sign-in is configured. Without company sign-in, codes and delivered
  credentials name the request's own origin. A server that omits
  `company_sign_in` predates it and offered device codes only with company
  sign-in. Partial configuration refuses as `oidc_misconfigured`; an older
  server without discovery requires an explicit API token until its operator
  upgrades it. The wizard retains the discovery
  refusal and offers **Use API token**, **Edit connection**, and **Choose another
  home**, including when company sign-in is misconfigured.

## Approval and delivery

`yoke machines pending` lists code, machine, requested-by identity and expiry for
the signed-in organization. `yoke machines approve CODE` and
`yoke machines deny CODE` show the viewer and machine before recording a decision;
codes accept either case. `--json` emits structured function replies. A local
universe instead explains that other computers cannot connect and points to
`yoke self-host init`.

The CLI and shared `/machine-approval[/CODE]` workbench page use
`machine_authorization.get` and `machine_authorization.resolve`. The read returns
`authorization` with code, machine name/ID, platform, expiry, decision, current
state, viewer and requested-by identity; resolve takes `{code, action: approve|deny}`
and returns that decision. The pending function is `machine_authorization.pending`.
Hosted routing selects the organization and hands its code to the engine store.

Only an active human org member can approve their own machine. The first decision
binds the code to that person; another actor cannot take it over. An identical
decision can be repeated, while an opposite decision refuses. Credential issuance remains engine-owned atomic
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

## Approval page

The selected request shows one shared card headed **Approve this machine**.
It shows the real machine name (omitted when absent), platform and full machine
ID, uppercase **Match code**, **Requested by** when bound, organization,
**Approving as**, and the viewer's local expiry time and zone. Identities use
the supplied name and actor number; **This machine will act as you** explains
the approval. An older server without viewer facts shows **your signed-in
account** and asks its operator to upgrade. The UTC instant stays in the time
element. Approve only if the code matches your terminal.
**Approve machine** is the primary action; **Deny** authorizes nothing.
The card can also be embedded beside a request list, where its heading receives
focus. A direct approval link focuses **Approve machine**. Neither an absent
URL code nor an unavailable code offers a manual code-entry form.

A first organization connection shows four setup steps, with Connect machine
active and the preceding steps complete. The same visit shows every step
complete after approval. Later connections omit the bar. This follows the
organization's machine registry, without a caller-supplied first-run marker.

Approval shows **Machine connected**, a green success line, and a separate
orange **Return to your terminal** callout. The approved facts omit expiry
and the code-matching hint. A denied request says **Nothing was authorized**.
Expired requests show their local expiry when their stored facts remain
available; no client promises a replacement code automatically. Start a new
connection with `yoke connect` from the terminal. A consumed request says it
was already answered and directs you to Machines or a fresh connection.
Membership refusals name sign-in recovery, and a failed write keeps the actions
available for retry without reporting success.
An owner mismatch says the connection was already handled by the bound person,
using a name only when an existing read supplied it, otherwise **another person
in your org**. If that was not you, ask them or an admin to retire the machine,
then run `yoke connect` again. The refusal never discloses a new identity.
The installer and connect wait stop on expiry; neither rotates codes silently.

In a local universe the page makes no approval reads. It explains that other
people and computers cannot reach this universe, gives `yoke self-host init`,
and links to the [Self-host guide](https://github.com/upyoke/yoke/blob/main/docs/self-host.md).
The shared notice also has a token variant: a token does not make a local
universe reachable from another computer.

Inspection may read an expired or consumed record to display its outcome,
but resolve and poll still refuse expired or consumed codes. A record removed
by pending-store expiry cleanup is unavailable; membership and ownership still
protect reads. Light and dark themes share the same card and narrow layouts.

## Decide as the signed-in actor

Run `yoke machines pending` to see waiting requests, then
`yoke machines approve CODE` or `yoke machines deny CODE` to record your personal
decision. Read the returned decision and approver, and finish polling
from the original machine. These operations never accept a caller-supplied
owner, org, or credential.

On a hosted connection (`https://app.upyoke.com/api/orgs/<slug>`), the selected
organization scopes the request. See [Hosted org administration](hosted-org-admin.md).
An older server refuses a missing command with `function_version_skew` and its
minimum serving version. Connect with an explicit token using
`yoke connect <server> --token-stdin`, or ask the server operator to upgrade.

## Shared schema

The `yoke-contracts` wheel ships `yoke_contracts/machine_authorization.schema.v2.json`,
generated from the request and response Pydantic models. Load it with Python's
`importlib.resources.files("yoke_contracts").joinpath("machine_authorization.schema.v2.json")`,
or read that path from the pinned wheel in another language. Validate a body
against its named `$defs` entry while retaining the document's other `$defs`
for references. The `x-http` section names the endpoint, request model, success
model, error outcome's HTTP status and body model, and retry policy. Start and poll requests are shared across hosting modes.

`MachineAuthorizationStarted` and `MachineAuthorizationApproved` define success.
`MachineAuthorizationPending`, `MachineAuthorizationDenied`,
`MachineAuthorizationExpired` (including consumed), `MachineAuthorizationSlowDown`,
and `MachineAuthorizationUnavailable` define poll outcomes. Other diagnosed
refusals use `MachineAuthorizationRefused`. Recovery text is optional on the wire: self-host supplies `message`, and Cloud
supplies `detail`. Both are explicit fields in the shared refusal model; the CLI
retains supplied recovery text in fatal diagnostics. Cloud credential refusals
use HTTP 409; missing machine identity uses 400, malformed requests use 400 or
413, and retryable credential unavailability uses 503. The strict schema rejects
unrecognized response fields. Secrets are excluded from model repr and
client validation errors. The CLI and self-host route use these models;
`parse_authorization_response` also checks known poll statuses. Origin and API
authority checks remain required after body validation.

Regenerate after changing models with
`yoke dev run -- python3 -m yoke_contracts.machine_authorization_schema`.
Check drift with the same command plus `--check`; the contract test also fails
on byte drift. A breaking wire change requires a new schema version and the
linked consumer's tests against the exact candidate wheel. The schema's v2
identifies its contract independently of the wheel's release version.

Shared client helpers are `authorization_origin`, `same_origin_url`,
`credential_api_url`, and `parse_authorization_response`, with
`BROWSER_VERIFICATION_PATHS`, `POLL_OUTCOMES`, and `RETRYABLE_POLL_ERRORS`.

Hosted lifecycle delivery accepts qualified instants or aware Python datetimes
for occurrence and expiry. Numeric epochs, naive dates and empty supplied clocks
refuse. Stored decision clocks are native; owned occurrence, expiry and end
context fields and audit receipts use fixed-six UTC RFC3339Z or null. Expiry is
an inclusive comparison of instants, independent of database session timezone.


## Hosted code handoff

After sign-in and organization selection, Platform calls registered
`machine_authorization.handoff` in the selected organization's engine. Only
an active `hosted_service` identity holding `hosted_service.deliver` on the
explicit engine `org_id` may call handoff or `machine_authorization.handoff_poll`.
Human members and admins cannot call either function. Both registry and
client-readable floors are `next-release` until a release carries them; roll
the engine forward before enabling these calls in the hosted consumer.

Handoff takes `{device_code_sha256, user_code, machine_id, machine_name,
platform, expires_at, org_id}`. The digest is lowercase hex SHA-256 of the
original device secret; never send the raw secret to handoff. `user_code` is
four characters from `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`, such as `K7F2`.
Machine ID is a UUID; name and platform are nonempty, at most 150 and 80
characters. Expiry is qualified RFC3339, after now and within the engine's
ten-minute code TTL. Org ID is the positive **engine** organization ID,
never Platform's registry ID or an inferred default.

Success returns `{authorization: {user_code, expires_at, state: "pending"}}`
with canonical UTC expiry. Identical pending replay returns the same row;
a changed or closed request under its digest refuses `device_code_taken`.
Another row holding the match code refuses `match_code_taken`. Issue a new
secret and match code on either collision. Expired input refuses
`authorization_expired`; malformed or excessive expiry refuses
`authorization_expiry_invalid`. An unknown engine org refuses
`authorization_org_unknown`; a wrong identity or org grant refuses
`permission_denied`. Correct malformed fields after `authorization_refused`
or `authorization_handoff_invalid`; no request is replaced on refusal.

Handoff uses `machine_authorization_codes`, with no requester actor until
a signed-in member decides. Inspect and resolve still use this record and
personal approval. Handed-off rows have no per-client capacity key; they
count toward the same 128 pending-code server limit. `authorization_capacity`
requires finishing an approval or waiting for expiry. Expired rows are pruned
by the existing expiry rule during another start or handoff.

### Hosted polling

Platform's public route rate-limits each terminal, then calls authenticated
`machine_authorization.handoff_poll` with `{device_code, machine_id,
machine_name, org_id}`. Poll takes the **original raw device secret**, plus the
same engine org ID used at handoff. The function checks the service's grant
and the stored code's exact org before calling the existing domain poll.
It bypasses the engine's public route admission, so many hosted terminals do
not share Platform's proxy-address bucket. Public self-host admission is
unchanged; this is no new public endpoint or credential store.

The result is `{authorization: {state, machine_id, token?}}`. State is
`pending`, `approved`, `denied`, `expired` or `consumed`, projected from the
existing poll outcome. Only `approved` includes `token`, once. The approving
member's live membership and machine ownership still gate delivery, and
consumption and issuance commit together. Concurrent polls yield at most one
raw token. A failed mint rolls consumption back. Network loss after delivery
requires a new terminal connection; the token cannot be replayed.

Both functions use handler-managed idempotency. The dispatcher neither caches
nor replays polling credentials; the one-time-result guard also excludes them
from detailed debug captures. A reused request ID polls current durable state.
`authorization_unknown` requires a fresh connection; `machine_identity_mismatch`
requires the original machine and consumes nothing. Credential and actor
refusals retain their named code and recovery. Platform maps the result to
its public status, org slug and API URL; an engine function envelope itself
uses the normal function-call transport. Database failures refuse as
`authorization_store_unavailable`; restore database health before retrying.

The hosted consumer must adopt both explicit-org payloads and prove its real
routing against the exact merged engine candidate. Engine source tests do
not prove hosted route adoption. Existing hosted routing remains until that
consumer cutover; the consumer keeps Members panels until the pinned Team
destination is available.
