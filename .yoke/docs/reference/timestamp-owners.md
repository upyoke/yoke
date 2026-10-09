# Timestamp owners

This records native clock writers and their explicit wire boundaries.
The shared contract is in [timestamps](timestamps.md).

Invites retain native creation and acceptance instants; list projections format
those declared fields as fixed-six UTC/null. Organization seed, external identity
link and release-note writes use the shared native SQL adapter. Release-note
pipe output formats only its creation clock; its default version remains a UTC
calendar date. Role and permission seeding also binds native creation clocks.
GitHub binding and installation payloads format only verification/sync clocks
as fixed-six UTC/null, preserving opaque repository and account identities.

Release build metadata validates its supplied clock before replacing output,
and emits fixed-six UTC. Relay installation/failure receipts and API JSON logs
share the canonical formatter. Board timing retains native wall instants and
formats its declared event clocks before emission; durations remain monotonic.

Landing history and reconstructed Git facts retain native instants; their
payloads format only the declared landing clock. Queue observations outrank Git
committer clocks, with microseconds preserved. Unknown queue observations are
null; supplied malformed clocks refuse before recording. Additive GitHub binding
convergence declares the same native last-sync clock type as fresh birth.

Item mutation preparation retains aware instants. Item SQL writers derive their
clock-field ownership from the finite stored roster and bind through the native
adapter; nullable declared clocks stay null and malformed supplied clocks refuse
before the item write. Bulk updates retain their transaction and binding guards.

Strategy document, revision, archive and checkpoint writes bind native instants.
CAS compares qualified instants rather than display strings, preserving distinct
microseconds across database timezones. List/detail/revision JSON, generated
headers, ingest reports and checkpoint CLI output format their declared clocks
as fixed-six UTC/null; revision content bytes and content digests stay unchanged.
Board command JSON formats its native timing clocks at the output boundary.

Actor birth, approval preparation, universe-setting and migration-audit writes
retain native clocks. Session drift/rework and presentation ordering compare
aware instants; naive external presentation observations are rejected. Shepherd
pipe output formats native instants; its verdict date remains a UTC date label.

Path claim, amendment, target planning/materialization and snapshot writes bind
native clocks. Claim-age and Pack freshness reads preserve native microseconds;
malformed internal clock facts refuse instead of assuming a timezone.

Org and project role grants bind native clocks. Strategy section CAS, cached
render headers and staleness checks compare instants. Board calendar buckets
project native instants to UTC dates; age windows use aware timestamps.

Hook envelopes and new Progress Log entries format six fractional digits;
event SQL binds native clocks. Recent-session attribution compares aware
instants at its exact 30-minute boundary, including microseconds.

Dispatcher ledger and workflow-dispatch intent retention use native cutoffs;
the exact cutoff survives while a row one microsecond earlier expires.
Pending dispatch custody never expires. Lint and hook completion lookups bind
native window bounds. Hourly hook/tool reports format bucket instants as
fixed-six UTC while durations and coverage remain numeric facts.

Local and self-host universe import authority/credential writes bind native
clocks. New archive freeze and source-authority receipts format fixed-six UTC;
archive contents and existing receipt bytes retain their custody. Resume notices,
path override envelopes and capacity/performance report clocks use the shared
formatter at their owned JSON boundary. Opaque identifiers remain unchanged.

The pending resume notice is mutable state. Permanent conversion repairs only
its required `reactivated_at` clock using existing episode, heartbeat or offered
facts. Released claim target descriptors, counts and opaque fields remain intact;
missing valid owner evidence refuses before any scalar conversion.

New baseline artifact metadata formats its capture clock as fixed-six UTC and
binds the corresponding creation instant natively; existing artifact bytes stay
unchanged. Registry/board render headers and timing-log wall clocks use the shared
formatter. Artifact filename dates remain labels. Current observation birth
fixtures declare native clock columns; historical conversion fixtures retain TEXT.

Path-claim CLI JSON and body renderers format owned instants; worktree lane
responses normalize declared clocks before model validation. Doctor receipts bind
native run clocks and format only their response projection. Done bookkeeping
and merge marker writes retain native landing facts, including null unknowns;
provider corrections accept qualified RFC3339 and compare native instants. Queue
refresh cadence keeps native cutoffs and facts across database timezones.

New dispatcher result digests and public/CLI payloads apply the shared native
clock JSON projection, preserving opaque strings, integers and existing receipt
bytes. Current board and session-message fixtures declare native clock columns;
calendar-day rollups remain dates. Git epoch seconds stay a provider protocol,
with fixed-six UTC formatting when projected into a request.


Merge-lock expiry and temporary-environment cleanup bind native cutoffs and
retain the exact cutoff, including microseconds. Their SQL clocks remain native;
relayed lock payloads and temporary-environment pipe output format declared
clocks. Manual environment clock updates validate qualified instants before
binding. Task-status writes bind a native wall clock.

New reflection fallback clocks, YAML update clocks, command event envelopes,
adoption evidence and fleet-rehearsal receipts use fixed-six UTC. Database
read diagnostics format native datetimes while calendar dates retain date ISO.
Board item classification keeps nullable native update facts and sorts done
items by those instants without an empty-string SQL fallback.

Board session ages consume native starts and ends with explicit null absence; malformed clocks refuse rather than inventing UTC. Daily velocity fallback queries compare native transition instants with native cutoffs, while calendar rollups retain day strings. Strategy revision windows retain all native history before projecting UTC days and applying the day bound. Reflection persistence fixtures mirror native timestamp ownership, with exact microsecond dedup across qualified offsets.

GitHub token facts retain native aware issued/expiry instants through authorization and GraphQL refresh telemetry; explicit numeric token ages and JWT seconds remain duration/protocol fields. Qualified provider clocks use shared strict ingress. Actions wait-run projects only its owned updated_at to fixed-six UTC or null, and stall decisions retain native precision without guessing naive or malformed clocks.

Board pricing binds native offered instants; session durations parse owned start/end facts with explicit null absence. New typed board datetime values use fixed-six UTC, and archived typed query parameters normalize only in the replay lookup without modifying the supplied payload or its durable bytes. Calendar date tags remain calendar values.

QA requirement creation, waivers, plan snapshots, materialization, rematerialization, standalone executions, and new review audit/bundle rows generate aware native facts. Shared insert constructors own backend adaptation; direct SQL writers use the existing instant_parameter only at binding. Original capture start/proof values and immutable review bundle documents remain unchanged.

Board replay probes coverage of native aggregate and scalar reads before rendering them. An archived payload without the current figure omits that figure rather than executing a query it never recorded. The version-2 baseline fingerprints and archived payload bytes remain frozen; live collection still records the current native SQL plan.

Worktree registration, path/commit recording, terminal cleanup and lane release bind native instants at SQL ownership, with one shared release/update fact per mutation. Actor UI preferences likewise bind native updated_at; preference values and timezone names retain their own non-instant semantics.

QA CLI/batch/browser run writes generate native start/completion facts for the existing finite run writer. Requirement retraction, supersession and target rebinding, method seeding/registration, project defaults, review bundle creation and host-wait completion bind native SQL clocks; supersession and rebind receipts retain native facts internally. Host-wait queue JSON remains an explicitly formatted six-digit wire owner.

Project registration, structure writes, infrastructure creation, capability repair/seed/secret metadata and GitHub sync receipts bind native SQL instants. GitHub installation and repository binding helpers accept native verification facts and adapt at each backend binding. Project retirement retains a native nullable fact, compares instants on repeat calls and explicitly formats its event context clock.

Overview universe and machine latches retain native facts on both first activation and subsequent reads. Relay/session registration, recency and harness ordering compare parsed instants rather than PostgreSQL display strings; nullable clocks stay absent. The function response boundary formats these native values once for the wire.

Deployment acceptance runs, stage requirements/receipts, membership admission/retry, settling, preview claims, execution/completion and stage entry generate native facts. Stage re-entry retains the original native clock. Environment delivery accepts an aware fact or qualified wire instant at its owner, defaults only on None and adapts at SQL binding; copied frozen requirement snapshots and executor receipt bytes remain unchanged.

Ephemeral terminal cleanup, flow creation, gate satisfaction, workflow canon selection, new artifact rows, task path bindings, continuity moves, test-machine configuration and item JSON-section clocks bind native SQL facts. Machine report writes and rereads share native reported_at values; the function response owner formats new wire payloads. Existing artifact metadata and item JSON content stay opaque.

Deployment-run snapshot projection parses only the existing RUN_INSTANT_FIELDS into native facts, binds native SQL parameters and formats new snapshot digests through the owned wire boundary. Equivalent offsets replay identically; one-microsecond changes retain destination CAS refusal. Artifact identities, requirement snapshots and stored historical receipt bytes/digests are not rewritten. Active deployment validation fixtures use native clock columns/defaults.

Workflow publication, built-in convergence, current-version selection, execution instructions and QA defaults bind native facts only at SQL ownership. Strategy document linking and claim registration/release retain native receipt clocks; message reseating shares the link fact. Strategy event contexts explicitly format new clock payloads. Published workflow definitions, digests and prior immutable rows remain unchanged.

Field-note disposition/correction, posture waiver, path context/override and path-integrity run/repair clocks bind native facts at SQL ownership. Promotion recovery compares the stored native reservation clock without PostgreSQL display conversion. Pack reports retain native facts through receipts. Calendar-day review boundaries become explicit UTC midnight instants; native review facts format at the human-message owner. Abandon audit rows share one exact requested/applied clock.

Rehearsal freshness compares native aware instants at the exact microsecond boundary. Missing or invalid rehearsal evidence remains expired; invalid explicit current clocks refuse, and only None generates a current fact. PostgreSQL fingerprint catalog queries move unchanged to their own reader, preserving schema/digest computation. Epic heartbeat validation consumes native database values with shared strict ingress, without accepting PostgreSQL display text or inventing UTC for naive values.

Doctor session/reclaim, reflection, coordination, QA and lane checks bind native cutoff/window instants with microsecond precision. Sweep and heartbeat age readers use shared strict ingress; malformed clocks produce a refusal finding rather than guessed UTC or a green result. Project-local reflection coverage adapts its shared native cutoff at SQL ownership. Reclaim and coordination message clocks explicitly format as UTC wire instants; filesystem modification ages remain numeric file metadata.

Lifecycle withdrawal/approval consumption, deployment approval, driver liveness and new run creation generate native facts. Creation shares its native fact with UTC calendar run-ID allocation, validates before DB access and adapts at the insert owner. Approval domain receipts and public model facts remain native; new event/JSON clock projections use fixed-six UTC. Commit-attestation recorded_at remains an explicit wire field inside newly authored receipt JSON; existing receipts remain opaque.

Machine verification, operation and mission preparation receipts generate native SQL facts. Capability and receipt readers retain aware clocks, with nullable verification absence preserved. New verification history entries format only their declared clock; earlier receipt entries, submission identities and check evidence remain opaque and unchanged. Replay parses only the declared clock and operation response JSON explicitly formats it as fixed-six UTC or null. SQLite storage is an explicit canonical wire boundary.

Conflict surveys retain native observation facts; new persisted envelopes format their declared clock and absent status observations remain null. Survey reservations and result CAS writes bind native section clocks. DB-claim amendments share a native SQL/event fact and format new reviewed-negative JSON stamps at their owner; frozen historical attestations are carried unchanged. Derived project fact inserts and updates share one exact native observation clock.

Doctor blocked-item, task heartbeat, undeployed-item and backlog ages compare native aware instants through timedeltas, retaining their existing thresholds at microsecond boundaries. The Unix epoch is valid evidence. Missing clocks remain unknown and malformed stored clocks produce refusal findings rather than quiet passes. The private epoch parser and its reexports are retired; new report headers and branch-protection drift events use fixed-six UTC wire clocks.

Merge-audit report generation and done-transition transport payloads are wire owners, so their new clocks use the shared fixed-six formatter. Their timestamps are not SQL parameters. Doctor meta fixture schema derivation stays lazy until the disposable connection is prepared.

Doctor close-out checks query native merge and queue-landing clock nullness directly, without empty-text substitutes or comparisons. A completed item lacking a merge fact still warns; a real native landing fact still identifies active work needing close-out.

Onboarding run and checklist writes share native creation/update facts across helper calls and adapt only at SQL ownership. Run reads retain native clocks. Deployment reconciliation compares the stored native update fact at microsecond precision, formats only new supersession metadata clocks and parses only those declared facts when rereading; unrelated evidence remains opaque. Existing additive onboarding schema helpers live with their schema declarations. Machine-QA Pack method projection binds native creation/update clocks without changing immutable Pack method documents.

Session inventory compares native heartbeat and tool-activity cutoffs at exact microsecond boundaries. Machine capture recording shares a native fact across run and artifact inserts; merge-gate CI requirement/run writes retain native clocks. Actor-role and field-note handlers generate native facts for their strict SQL writers. Artifact evidence, captured clock-looking text and verdict identities remain opaque.

Chain checkpoints retain native completed_at facts for domain callers and format only that declared clock in new persisted envelope JSON; readers and clearing parse that one clock strictly. Existing unrelated envelope evidence is opaque. Reclaim and handoff share native facts through their SQL writes, adapting each parameter at ownership. Shared compact JSON and function-response serializers project native checkpoint facts to fixed-six UTC.

Session focus rotation parses and binds only its declared clocks, retaining prior native facts and null absence. Idle-end and termination/reap writes generate native instants; message wake expiry SQL binds the exact native comparison clock. Steering SQL creation binds one native fact and its message drain receives a native current fact. Cleanup janitor_now and wake-window status projections are explicit fixed-six event/status wire fields.

GitHub credential refresh/access timing retains native aware instants internally and strict shared ingress rejects naive clocks. Document reads parse only declared refresh and cached-access expiry fields; new file writes format those fields as fixed-six UTC, while unrelated evidence is opaque and reads preserve bytes. The existing immutable standalone helper bundle now includes exact shared-kernel bytes, keeping portable execution independent of product imports.

Session human output parses native or qualified clocks strictly and preserves deliberate minute/age presentation. End-blocker message clocks format as fixed-six UTC, and stale countdowns retain positive microsecond order before rounding to minutes. Malformed Doctor receipt clocks report unverified health. New wizard log clocks and native field values format at the append owner; previous lines and opaque text remain unchanged. Runner provider-token expiry and current clocks use strict shared ingress with exact inclusive expiry and secret-free refusal messages; authority signing bytes are unchanged.

Snapshot chunk staging and capability CAS/Pulumi creation bind native facts at their SQL owners. Capability settings argument registration lives separately from the existing CAS workhorse; Pulumi row locking/creation has one dedicated owner and uses the canonical capability type constant. Epic-task synchronization no longer attempts an ignored insert into a retired history table; the canonical native task transition recorder remains the history owner. The disposable capability fixture uses native clock columns. These changes preserve settings CAS, transaction and opaque evidence behavior.

Shared session holdings use native release and overlap facts, with instant-based steering-window keys across offset representations. Invalid release clocks refuse rather than disappear. Historical path/coordination observations with no known release retain a null clock and explicit internal held state, so absence cannot turn history into current authority. Remount receipts use native strict clocks internally and finite fixed-six file projection; invalid receipt clocks refuse aliasing without rewriting bytes, and the existing less-than expiry cutoff retains microsecond precision.

Resident observation batches parse captured clocks as native aware facts, bind monotonic heartbeat comparisons at each SQL owner, and format only the declared event-envelope clock. Missing/invalid captured clocks have typed refusals. The composed API fixture declares its finite instant columns natively. Legacy explicit SQLite migration validation retains native duration facts and formats the failure-audit start at its SQLite boundary without losing microseconds; it does not grant control-plane apply authority.

HTTP item responses format their finite creation, update and merge clocks before
response-model validation. Native microseconds survive across database timezones;
unknown merge clocks stay null and malformed supplied clock facts refuse.

Queue observation records retain native freshness and semantic-change clocks;
record payloads format fixed-six UTC/null. Arming notice lookup matches only its
qualified clock suffix and reuses the stored immutable key for the same instant.
New episodes format canonical keys, and native landing/notification writes retain
microseconds across database timezones. Existing notice bytes remain unchanged.

Git commit-time ingress converts its integral epoch protocol to a native aware
instant and uses null for an unreadable commit. Nonempty malformed or unbounded
provider clocks refuse. Close-out forwards the native fact; its request payload
formats only at the existing merged-at owner.

Current queue birth fixtures store canonical SQLite boundary clocks. Ejection
clearing compares native arming instants; a rearm one microsecond later remains
visible even if the predecessor notice is delivered.

Named entry ingress forwards native default and supplied qualified instants;
blank or malformed supplied clocks refuse before the entry writer. Governed
exception audit fingerprints bind native start/completion clocks through the
shared adapter, retaining explicit backup/no-backup authority requirements.

Governed apply/rehearsal helpers retain native audit and result clocks. Both
audit writer surfaces use one finite parameter owner; native update clocks keep
nullable absence and reject malformed values before mutation. New verification
command outcomes and console projections format their declared clocks as
fixed-six UTC. Current migration capability/audit fixtures declare native types.

Claude job-record reads parse only their declared updatedAt clock as a native
aware instant. Missing clocks stay unknown; malformed clocks refuse the bounded
read without changing foreign bytes. Idle eligibility compares native timedeltas
at microsecond precision before reporting integer durations. OS process-start
and foreign session-start NumericDate protocols retain their process identity
role; live-session and newest-spare protections remain in place.

Compact GitHub mirror flags create native instants and adapt only at SQL binding;
full-body synchronization clears the clock to null. Invalid generated clocks
refuse before the best-effort savepoint. Severity initialization shares the same
SQL adapter, retaining native PostgreSQL facts and canonical SQLite boundary
clocks without changing the existing conflict-preserving seed behavior.

Disposable backlog graph fixtures create native clocks and parse provided clocks
through the shared strict ingress. The existing finite stored-instant roster
selects SQL parameters for items, worktrees, generated tasks, events, deployment
runs and QA records; explicit SQLite formats at binding. Null optional clocks
and opaque body/result evidence retain their meaning. Empty or malformed clock
inputs refuse instead of defaulting to the current time.

Project, session, process/work/path claim and strategy execution seed helpers
bind native SQL clock facts. Deterministic strategy and machine-QA seed clocks
are parsed once at their declared owners; release/end absence remains null.
Minimal explicit SQLite machine fixtures format through the shared SQL adapter.
