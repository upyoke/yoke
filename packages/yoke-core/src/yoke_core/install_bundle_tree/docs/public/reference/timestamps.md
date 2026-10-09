# Domain instants and UTC wire values

`yoke_contracts.timestamps` owns the Python instant boundary. Database writers
use `utc_now()` or `parse_instant(value)` to bind an aware `datetime`. Owned
wire values and files use `format_instant(value)` or `iso8601_now()` to produce
`YYYY-MM-DDTHH:MM:SS.ffffffZ`. Optional unknown values are null where the owner
permits absence. Fractional zero padding does not recover measurement precision.

Supplied inputs require a valid calendar and an explicit UTC offset. Naive
datetimes, date-only values, unknown `-00:00` offsets and precision beyond
microseconds refuse as `invalid_instant`; supply a qualified instant instead.
Offset-qualified inputs normalize to the same UTC instant without dropping
microseconds. The runtime parser never guesses a timezone or repairs history.

`actor_state.set_actor_enabled(..., now=...)` requires an aware `datetime`.
Its owning handler uses `utc_now()`; an adapter with a qualified wire input
calls `parse_instant` before invoking the domain operation. Revocation and audit
parameters bind as native UTC datetimes on PostgreSQL and canonical fixed-six
strings on SQLite. A string or naive datetime refuses before any state change.

`db_helpers.instant_parameter(conn, value)` is the shared SQL adapter for aware
native values and optional nulls. It binds a UTC datetime on PostgreSQL and
canonical fixed-six text on SQLite; callers parse supplied wire inputs before
invoking it. `json_helper.dumps_compact`, `dumps_pretty` and file dumps apply
`temporal_wire`, so native values cross JSON boundaries canonically while
opaque strings remain byte-for-byte values.

One-time governed conversion lives in `stored_instant_conversion`, with a
frozen column roster supplied by permanent migration history. It checks all
source columns before changing types and combines each table's alterations
into one rewrite. Approved historical calendar values assume UTC; optional
blanks become NULL, and specifically approved owner-creation repairs replace
missing item updates or malformed Ouroboros observations. These are explicit
historical assumptions, not recovered facts or future input fallbacks. The
caller retains the restore point, transaction, serving floor and receipts;
append-only UPDATE/DELETE guards remain enabled during type conversion.
Permanent history freezes all 265 columns across 125 tables. Excess historical
fraction digits are dropped at microseconds. Its finite mutable-document policy
repairs only declared usage, episode, resume-notice, driver, QA-wait and
machine-decision clocks
using existing owner facts, preserving other document fields. Unknown optional
usage observations become JSON null. Repairs use compare-and-set predicates; a
concurrent writer refuses instead of losing newer facts. All document repairs
are prepared before any type change. The owned progress view is reconstructed
inside the same transaction; stored relay plan/model observations, plan reset
clocks, capacity observations and health failure/quarantine/refusal clocks follow
finite owned paths. Optional unknowns become null; invalid supplied history uses
the relay observation owner fact. Model retirement calendar labels and opaque
fields retain their meaning. Unowned dependents or custom view metadata refuse
before any view is dropped. No immutable or signed document is rewritten.
The serving catalog probe also checks declared native instant types: matching
column names with TEXT or timestamp-without-zone storage cannot prove that a
build requiring TIMESTAMPTZ can serve that database. The governed serving floor
remains an independent requirement.

`temporal_wire(value)` converts native datetimes within result dictionaries and
sequences, preserving nulls. It leaves strings untouched: timestamp-shaped
prose, identifiers and immutable historical documents retain their meaning and
bytes. Each mutable document owner validates its declared timestamp fields at
ingress. Function response serialization and the idempotency result ledger
share this conversion, so HTTP, CLI and local response envelopes agree.

Hosts share `ui/contracts/timestamps.ts` and its emitted declaration. The
browser runtime is `ui/static/timestamps.js`, compiled from that source.
`formatInstant` accepts qualified RFC3339; `formatDatabaseInstant` adapts
PostgreSQL's qualified text output. Both retain all six fractional digits.
`instantMicros` compares exact microseconds as bigint. `instantFromDate`
truthfully pads a browser Date's millisecond precision with three zeros.
Neither database strings nor cursor keys travel through a fractional Date parse.

Standalone Node consumers use `yoke_contracts/timestamps.mjs` from the
`yoke-contracts` wheel. It contains the same emitted bytes as the browser helper,
with no UI aliases or dependencies. Python packaging consumers read it with
`importlib.resources.files("yoke_contracts").joinpath("timestamps.mjs")` and may
copy those exact bytes into a Lambda StringAsset. The wheel also includes
`time_sql.mjs`, identical to the emitted SQL projector. Consumers that cannot
install Python packages may vendor the exact `yoke_contracts/timestamps.py`
resource from that same wheel; retain its artifact identity instead of creating
a separate parser or formatter.

SQL JSON producers share `yoke_contracts.time_sql.instant_wire_sql(expression)`.
It projects native timestamptz to the same fixed-six UTC wire form, preserving
SQL NULL and the exact transaction clock. Native predicates keep their indexes;
only the owned serialization boundary uses this text projection.
`now_sql` returns native `now()` with an elapsed offset for indexed predicates;
fixed days/hours/minutes count 86400/3600/60 seconds across session timezones.
Calendar buckets declare their timezone at their owner rather than replacing
the instant clock with LOCALTIMESTAMP. Event envelopes and cursor payloads use
canonical fixed-six timestamps; cursor bounds parse back to native instants.
Old event, settled-message, ended-session and launch-history cursors refuse with an instruction to clear
them and reload. Settled-message history orders and binds native creation
instants, then uses the message id to resolve equal-instant ties. Launch records
and relay leases retain aware instants internally; their public projections
format UTC wire values. Launch-history bounds use native creation instants
and launch ids for ties. Relay expiry and registration windows compare
native instants at their half-open boundaries without truncating microseconds.
Session roster and history order native activity instants, preserving nulls in
PostgreSQL GREATEST. Ended-history cursors version and encode the exact canonical
instant plus session id; bounds bind native values. Effective model schedules
compare aware instants and keep their canonical catalog digest inputs unchanged.
Turn-posture ordering and coordination-claim acquisition, heartbeat, release,
and stale thresholds bind native instants. Claim records retain aware datetimes;
public claim and wait evidence format fixed-six UTC strings and preserve null.
Session registration, heartbeats, work-claim acquisition and release, terminal
checkpoint stamps and epic-task activity bind native instants. Claim release
intent matches the same native release instant. Reclaim decisions compare aware
activity across session, claim and open-call signals; their evidence formats
canonical wire values. Orphan-call closure keeps native endpoints and serializes
its sentinel envelope canonically. Claim duration milliseconds use integer
arithmetic rather than floating-point conversion. Hook command acquisition,
release, heartbeat and focus rotation bind the same native instant adapters;
pipe output formats native instants canonically. Active-session and released-claim
guards test SQL null directly, without empty-string timestamp fallbacks.
Prompt/completed-work facts, tool-call endpoints and promised-work holds use
native instants. Replayed calls retain one count, and late starts correct only
the endpoint. Invalid ingress refuses before state changes. Captured duration
uses exact integer microseconds with nearest millisecond ties rounded to even;
negative and over-ceiling intervals are rejected before rounding. Provider
recovery compares native activity and turn-end clocks, preserves exact backoff
boundaries and canonicalizes owned observation timestamps. Its resume budget
key is canonical UTC or an empty no-tool-activity identity; the governed migration
must normalize existing nonempty keys without changing attempt counts.
Process evidence normalizes its owned native-exit clock while retaining opaque
OS process-start identity bytes. Session and claim service-client JSON uses
shared temporal serialization rather than a generic datetime string conversion.
QA selection orders native actual starts before considering verdicts, with ids
breaking equal starts and null starts remaining ambiguous. QA summaries format
owned run, waiver and retraction clocks canonically. Shared age displays and
start-bound authority use strict instant parsing and exact elapsed units; only
null is absent. Harness health windows compare native clocks and format the
selected last-seen instant. Debug capture expiry requires a qualified instant
and closes at its exact deadline.
Durable QA run writes normalize owned clock columns before locks or mutations;
review completion fills only a missing endpoint and preserves capture start and
raw evidence bytes. Ordered QA execution creation, heartbeat and result endpoints
bind native clocks. Staleness preserves the exact thirty-minute boundary and
refuses malformed supplied evidence. Host FIFO compares queue instants and keeps
execution allocation ties; mutable queue timestamps require governed conversion.
Pipe diagnostics format native clocks at presentation, without timestamp
empty-string SQL predicates. New result JSON uses shared temporal encoding;
opaque strings and finalized historical roster/digest bytes remain unchanged.
Item execution-status clocks and finishing-time views emit canonical wire values;
finished-window SQL parameters retain the native cutoff microseconds. Frontier
ownership defense, resumed-claim recovery and chain-head freshness compare aware
activity clocks with their existing boundary rules. Only null is missing evidence;
invalid supplied clocks refuse rather than implying a resumable or stale state.
The universe fingerprint formats its organization creation instant canonically,
so a database session timezone cannot change identity. Earlier recorded actor
bindings that name another timestamp representation refuse the identity match;
re-record the binding with `yoke config bind-actor --actor-id <id>` against the
verified universe. No name or old-format matching is inferred.
Private-route qualification expiry preserves the opening instant's microseconds.
API-token issuance, use, revocation and audit bind native instants. Optional
expiry remains null; supplied expiry requires a qualified instant before insertion.
Browser-session and one-time sign-in link deadlines retain microseconds and
expire exactly at the deadline. Session cookie expiry responses use fixed-six UTC.
Token hashes, opaque diagnostic strings and cookie lifetime seconds retain their
existing contracts.
Machine registration, relay-seen stamps, credential rotation and retirement retain
native instants; public machine and credential records format canonical UTC.
Device authorization codes use one aware clock for expiry and pruning and expire
at their exact deadline. Their protocol lifetime and polling interval stay seconds.
Installed frontend events, signed attribution cookies and one-time handoffs
use the same contract. Old numeric expiry payloads are refused and reminted.
The collector validates and normalizes qualified event times before storage.
Redemption expiry and rate-window starts are native database instants; rate
windows retain their 60-second UTC epoch alignment, including before 1970.
Historical INTEGER rate-window starts explicitly use epoch seconds during
one-time governed conversion.
Physical-copy lock metadata formats its diagnostic start instant canonically;
the file lock remains admission authority even when diagnostics are unreadable.
Node SQL producers import `instantWireSql` from `ui/contracts/time-sql.ts`
or its compiled `ui/static/time-sql.js`. The TypeScript source is generated by
`yoke_contracts.time_sql.instant_wire_typescript()` from the Python expression;
refresh that source when the projector changes, rather than maintaining a
second SQL template. Expressions are caller-authored SQL, never untrusted input.

After changing the TypeScript helper, run the pinned UI compiler from the UI
directory, then commit its runtime and declaration output together:

```text
node node_modules/typescript/bin/tsc --project contracts/tsconfig.json
node node_modules/typescript/bin/tsc contracts/timestamps.ts contracts/time-sql.ts --strict --target ES2022 --module ESNext --outDir static
cp static/timestamps.js ../../../../yoke-contracts/src/yoke_contracts/timestamps.mjs
cp static/time-sql.js ../../../../yoke-contracts/src/yoke_contracts/time_sql.mjs
```

Calendar days retain an explicit bucket timezone. Durations retain their units;
elapsed process deadlines use a monotonic clock. JWT/OIDC NumericDate, AWS,
HTTP and native third-party formats remain external protocol encodings, with
conversion at the owning adapter. Internal signing does not turn an owned
timestamp format into an external protocol. Preserve historical immutable
receipt bytes; new generations use canonical UTC. Historical repairs and active
credential or operation cutovers require evidence from their existing owners.

QA catalog authoring compares native instants for its compare-and-swap token,
binds that instant in both changed and unchanged writes, and emits a canonical
six-digit UTC token. Equivalent qualified offsets name the same token; any
microsecond change remains a conflict. Plan detail and method-rollup timestamps
are canonical view fields. Deployment-flow succession compares native creation
instants and keeps the existing identity tie-break; composition freeze tests
SQL nullness rather than substituting text for a native clock.

Release candidate reads retain native completion and freeze clocks, combine
own-project and bound-project candidates by instant, and place null completions
last. Delivery membership keeps its precedence over recency, honest carried work,
freeze exclusion, and ancestry; all cutoff comparisons use native instants.
The deployment-run pipe boundary prints canonical native clocks and blank nulls;
the structured run view emits canonical clocks and null, while opaque strings
retain their existing representation. Overview completion windows bind the
exact native 24-hour cutoff, including microseconds.

The strict instant formatter requires a supplied instant. A nullable view field
preserves null before formatting; absence cannot be passed through the parser
or formatter as if it named a clock. Settlement authority reads a native marker
and tests nullness, including before its additive column has converged.

Items and deployment-history paging encode their native sort instant as a
canonical fixed-six cursor value and bind it natively on continuation. ID
comparisons preserve exact-instant ties; text column cursors remain opaque.
Learning-log review sorting places null first ascending and last descending,
with explicit null continuation predicates and unchanged ID tie order. Filed,
reviewed, archived and promoted clocks format only at their owned projections.
Capability verification chooses the newest native stamp across active GitHub
channels before formatting it; suspended channels still supply no authority.

Run gate cards project native requested/resolved clocks and decision answers as
canonical UTC while retaining actor authority and human decision records.
Removed-member custody compares exact native creation instants; missing source
creation proves no later custody, and malformed supplied clocks refuse. Removal
metadata is formatted at the card boundary without rewriting its stored record.

Epic dispatch writes native started/update clocks, validates supplied clocks
before scope or lane mutations, and generates unstarted chains with null starts.
Activation and advance retain honest attempt counters and exact clock values.
Progress notes and section clocks bind natively; receipt and pipe projections
format canonical UTC without rewriting receipt bodies. Cascade event envelopes
use the shared JSON encoder while heartbeat columns remain native.

Decision creation, individual answers, resolution and withdrawal admit supplied
clocks strictly before mutation, bind aware native instants, and keep absent
resolution clocks null. Decision events share the caller transaction and use
the event writer's canonical SQLite/JSON boundary. Run terminalization binds a
native completion clock and exposes a fixed-six UTC audit receipt.
Machine-authorization lifecycle delivery rejects unqualified and numeric clocks
before coercion. Its declared expiry, occurrence and end-context clocks serialize
as fixed-six UTC/null; other context strings remain opaque. Expiry checks compare
native instants inclusively, preserving microseconds and offset equivalence.

Relay model and plan-limit probe caches use native aware clocks internally and
canonical UTC/null probe clocks in their versioned JSON files. Obsolete numeric
cache shapes are discarded and reprobed; a future cache cannot prove freshness.
Elapsed cadence includes the lower boundary and excludes its exact expiry.
Model observations, plan-window resets and relay failure/quarantine/refusal
clocks format only as declared instant fields. Missing observations are null;
model tokens, retirement dates, report bodies and preserved payload digests stay
opaque. Quarantine validates a supplied clock before moving its payload.

Native captures parse only their declared exit and last-output headers as aware
instants; new headers and exit evidence use fixed-six UTC, preserving the raw
native streams. Missing headers remain unknown; malformed supplied headers make
an envelope unreadable, without a file-modification-time substitute. Supervisors
retain aware wall clocks, and silence subtracts exact native instants.
Session usage and machine capacity retain native observation clocks internally
and format only their declared wire fields. Missing usage observations are null.
Carried usage storage canonicalizes its observation while preserving unrelated
JSON facts; malformed clocks refuse before SQL or capacity probes.

Fleet readers retain native activity, launch, message, landing, decision and
report-delivery clocks through ranking and exact elapsed comparisons. Earliest
landing and latest decision selection compare instants, with explicit null and
identity tie order. Report JSON emits fixed-six UTC/null; calendar reset labels
remain human display. Delivery interval compare-and-set binds native values and
includes the exact cutoff without an empty SQL sentinel. Declared malformed
reset clocks refuse; missing resets remain unknown. Fingerprints still omit age.

Deferred hook observations retain native aware clocks until their telemetry
JSON payload formats the declared observation field. Required observations reject
null or malformed clocks before enqueueing; request text and monotonic queue ages
keep their own meaning. Transport retry, resident delivery and relay failure
diagnostics share the same fixed-six UTC formatter, preserving microseconds and
refusing naive clocks rather than assigning a timezone.

Deployment-start markers and Atlas reports format their declared clocks through
the shared kernel; report readers compare native instants without rewriting raw
captures. CI reuse accepts only qualified external clock evidence within its
known window; malformed, unqualified or future evidence cannot skip the suite.

Deployment drivers retain native attachment and heartbeat instants, comparing
the inclusive live-window cutoff without truncation. Their mutable JSON column
and refusal diagnostics format only declared clocks; raw capture paths remain
opaque. Malformed clocks refuse before custody reads or writes. QA wake notices
retain native sent clocks; their UTC hour/minute label is presentation only.

Item capability configuration binds a native creation instant and formats its
owned creation/verification response fields as fixed-six UTC/null. Carried-work
landing attribution compares native timedeltas at the inclusive ten-minute
boundary. Missing or invalid external Git clock facts cannot infer ownership;
malformed internal landing clocks refuse rather than assuming a timezone.

Owned writer and projection details are maintained in
[timestamp owners](timestamp-owners.md).

Browser snapshot and screenshot JSON and daemon state files produce canonical
fixed-six UTC clocks through the pinned Node kernel shipped inside the harness
resource bundle. Date's measured milliseconds are padded with trailing zeros;
no sub-millisecond precision is invented. Opaque screenshot filename suffixes
remain identifiers, and browser display-age calculations remain display owners.

Onboarding lock, report and checklist files, local-core state and UI daemon records generate fixed-six UTC clocks
with the shared formatter. UI daemon records retain native instants after file ingress and format their status JSON.
Resumed report clocks accept field-permitted null and validate provided clocks before rewriting the report;
historical source reports and opaque text stay unchanged. Hook-latency measurement uses native run-window clocks,
formats only the events-query argument and report fields, and keeps elapsed timing monotonic.

UI time elements publish qualified source instants with all six fractional digits; null publishes no machine clock.
Display ages and refresh counters remain measured in milliseconds. Hosted-frame, QA/workbench and card specimen
fixtures reuse the shared Date producer without changing historical versions.

Conversation mappings and process-anchor files publish fixed-six UTC clocks through the shared kernel; OS
process-start identity text stays opaque. Current routed-session fixtures bind native clocks and adapt only at
SQLite ownership.

QA daily summaries keep UTC day labels as dates; half-open windows bind native UTC midnight instants independently
of the SQL session timezone.

Notice, messaging, settlement, signing, export-name and fleet polling owners validate supplied clocks before reads
or actions; only null selects the shared clock. Qualified offsets normalize without losing microseconds. Captured
hook endpoints retain their timing owner. Scheduler fixtures declare native columns. QA wakes, parked ordering, hook
context and event relative bounds reuse this clock.

Surface-policy, approval, task-binding, workflow inventory and composition replies format declared clocks as
fixed-six UTC/null. Approval missing its required clock refuses with named recovery. Session identity/release
readers keep native instants; steering ties compare instants before claim ids. Chain event context, new triage
receipts and stale-browser diagnostics format their owned clock fields. Terminal settlement parses its optional
completion instant. Existing frozen snapshots, retained triage receipts, reports and digests stay opaque.

Merge receipts order present instants; steering reply cutoffs stay native. Doctor, pricing and hook report metadata
format clocks as fixed-six UTC/null. Report confirmation validates before connecting and binds native interval
clocks.

Strategy headers emit fixed-six UTC identities; parsing rejects invalid clocks as mangled headers. Archive
relocation compares canonical identities before file inspection, preserving matching file bytes, body hashes and
editor labels.

Source-authority receipts format metadata as fixed-six UTC/null and compare native freeze
watermarks before hashing. Private CONNECT-fence birth uses native freeze/retirement columns;
clocks validate before SQL. Credential files and archive diagnostics format owned clocks.
Existing receipt files, frozen fixture IDs and physical PostgreSQL row checksums retain bytes.
Generated board last-synced markers use fixed-six UTC in both CLI and engine paths.
