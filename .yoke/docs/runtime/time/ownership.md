# Timestamp owners

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Runtime](../index.md) > Timestamp owners
<!-- /yoke:breadcrumbs -->

This records native clock writers and their explicit wire boundaries.
The shared contract is in [timestamps](encoding.md).

## Work, session and delivery clocks

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

Path claim, amendment, target planning/materialization and snapshot writes bind native clocks. Snapshot, client-scanned materialization and target resolution retain Native clocks through internal calls and validate even reused targets; only SQL binds format SQLite clocks.
Claim-age and Pack freshness reads preserve native microseconds;
malformed internal clock facts refuse instead of assuming a timezone.

Idle wake eligibility validates aware native clocks and exact microsecond cutoffs. Report leases and hook settlement retain native instants and refuse internal wire/naive clocks. Cleanup age displays use exact timedelta minute flooring across valid UTC years. Hook envelopes and new Progress Log entries format six fractional digits;
event SQL binds native clocks. Dependency-edge creation and reconciliation validate Native clocks and format only explicit SQLite binds; reconciliation validates before its write transaction. Recent-session attribution compares aware
instants at its exact 30-minute boundary, including microseconds.

Dispatcher ledger and workflow-dispatch intent retention use native cutoffs;
the exact cutoff survives while a row one microsecond earlier expires.
Pending dispatch custody never expires. Lint and hook completion lookups bind
native window bounds. Hourly hook/tool reports format bucket instants as
fixed-six UTC while durations and coverage remain numeric facts.

The pending resume notice is mutable state. Permanent conversion repairs only
its required `reactivated_at` clock using existing episode, heartbeat or offered
facts. Released claim target descriptors, counts and opaque fields remain intact;
missing valid owner evidence refuses before any scalar conversion.

Path-claim CLI JSON and body renderers format owned instants; worktree lane
responses normalize declared clocks before model validation. Doctor receipts bind
native run clocks and format only their response projection; the live outcome scan binds its exact native three-day cutoff. Done bookkeeping
and merge marker writes retain native landing facts, including null unknowns; queue adapters parse local and relayed clock ingress, preserve native arming episodes, and format only request payloads and human landing text;
provider corrections accept qualified RFC3339 and compare native instants. Claim contention, run terminalization, minted web-session and strategy-ingest plan models retain native clocks; ingest CAS compares native plan facts and formats conflict reports; contention, terminalization and minted web-session results refuse internal wire/naive clocks; claim age uses exact timedelta second flooring; claim reports and terminalization responses format only their owned output leaves. Queue
refresh cadence keeps native cutoffs and facts across database timezones. Recovered arming episodes parse the stored instant before rebinding; completion attribution binds its new recorded clock natively. Collector refusal minute clocks format fixed-six UTC at their JSON leaf.


Merge-lock expiry and temporary-environment cleanup bind native cutoffs and
retain the exact cutoff, including microseconds. Their SQL clocks remain native;
relayed lock payloads and temporary-environment pipe output format declared
clocks. Manual environment clock updates validate qualified instants before
binding. Task-status writes bind a native wall clock.

Worktree registration, path/commit recording, terminal cleanup and lane release bind native instants at SQL ownership, with one shared release/update fact per mutation. Actor UI preferences likewise bind native updated_at; preference values and timezone names retain their own non-instant semantics.

Overview universe and machine latches retain native facts on both first activation and subsequent reads. Relay/session registration, recency and harness ordering compare parsed instants rather than PostgreSQL display strings; nullable clocks stay absent. The function response boundary formats these native values once for the wire.

Deployment acceptance runs, stage requirements/receipts, membership admission/retry, settling, preview claims, execution/completion and stage entry generate native facts. Stage re-entry retains the original native clock. Environment delivery accepts an aware fact or qualified wire instant at its owner, defaults only on None and adapts at SQL binding; copied frozen requirement snapshots and executor receipt bytes remain unchanged.

Ephemeral terminal cleanup, flow creation, gate satisfaction, workflow canon selection, new artifact rows, task path bindings, continuity moves, test-machine configuration and item JSON-section clocks bind native SQL facts. Machine report writes and rereads share native reported_at values; the function response owner formats new wire payloads. Existing artifact metadata and item JSON content stay opaque.

Deployment-run snapshot projection parses only the existing RUN_INSTANT_FIELDS into native facts, binds native SQL parameters and formats new snapshot digests through the owned wire boundary. Equivalent offsets replay identically; one-microsecond changes retain destination CAS refusal. Artifact identities, requirement snapshots and stored historical receipt bytes/digests are not rewritten. Active deployment validation fixtures use native clock columns/defaults. Smoke QA status retains nullable completion facts and projects its owned clock as fixed-six UTC or null.

New and existing workflow publication, including the publication module moved from the registry, preserve Native SQL clocks. QA successor reconciliation keeps the existing supersession instant through owned SQL ingress. Standalone recorded-landing client ingress retains a nullable Native merge clock and formats only its output leaf. Driver attachment constructors and internal reference clocks require Native values before SQL; stored attachment JSON retains its parse/output owners. Workflow publication, built-in convergence, current-version selection, execution instructions and QA defaults bind native facts only at SQL ownership. Strategy document linking and claim registration/release retain native receipt clocks; message reseating shares the link fact. Strategy event contexts explicitly format new clock payloads. Published workflow definitions, digests and prior immutable rows remain unchanged.

Field-note disposition/correction, posture waiver, path context/override and path-integrity run/repair clocks bind native facts at SQL ownership. Promotion recovery compares the stored native reservation clock without PostgreSQL display conversion. Pack reports retain native facts through receipts. Calendar-day review boundaries become explicit UTC midnight instants; native review facts format at the human-message owner. Abandon audit rows share one exact requested/applied clock.

Lifecycle withdrawal/approval consumption, deployment approval, driver liveness and new run creation generate native facts. Creation shares its native fact with UTC calendar run-ID allocation, validates before DB access and adapts at the insert owner. Approval domain receipts and public model facts remain native; new event/JSON clock projections use fixed-six UTC. Commit-attestation recorded_at remains an explicit wire field inside newly authored receipt JSON; existing receipts remain opaque.

Conflict surveys retain native observation facts; new persisted envelopes format their declared clock and absent status observations remain null. Survey reservations and result CAS writes bind native section clocks. DB-claim amendments share a native SQL/event fact and format new reviewed-negative JSON stamps at their owner; frozen historical attestations are strictly validated and carried byte-for-byte unchanged; new freeze stamps use fixed-six UTC. Derived project fact inserts and updates share one exact native observation clock.

Merge-audit report generation and done-transition transport payloads are wire owners, so their new clocks use the shared fixed-six formatter. Their timestamps are not SQL parameters. Doctor meta fixture schema derivation stays lazy until the disposable connection is prepared.

Onboarding run and checklist writes share native creation/update facts across helper calls and adapt only at SQL ownership. Run reads retain native clocks. Deployment reconciliation compares the stored native update fact at microsecond precision, formats only new supersession metadata clocks and parses only those declared facts when rereading; unrelated evidence remains opaque. Existing additive onboarding schema helpers live with their schema declarations. Machine-QA Pack method projection binds native creation/update clocks without changing immutable Pack method documents.

Chain checkpoints retain native completed_at facts for domain callers and format only that declared clock in new persisted envelope JSON; readers and clearing parse that one clock strictly. Existing unrelated envelope evidence is opaque. Reclaim and handoff share native facts through their SQL writes, adapting each parameter at ownership. Shared compact JSON and function-response serializers project native checkpoint facts to fixed-six UTC.

Session focus rotation parses and binds only its declared clocks, retaining prior native facts and null absence. Idle-end and termination/reap writes generate native instants; message wake expiry SQL binds the exact native comparison clock. Steering SQL creation binds one native fact and its message drain receives a native current fact. Queued-wake release clocks stay native or null through report aggregation and format only in report text. Diagnostic-retention receipts and relay outcomes retain Native deadlines; declared report evidence and CLI JSON project fixed-six UTC/null. OS pruning keeps its filesystem scalar boundary. Cleanup janitor_now and wake-window status projections are explicit fixed-six event/status wire fields. Run-driver execution, operator-waiver, notice and release routes pass native clocks to their strict attachment reader. The private browser sign-in gate formats only its owned JSON started_at as fixed-six UTC; process and identity values stay opaque.

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

Disposable backlog graph fixtures create native clocks and parse provided clocks
through the shared strict ingress. The existing finite stored-instant roster
selects SQL parameters for items, worktrees, generated tasks, events, deployment
runs and QA records and selects native types for missing additive deployment clock columns; explicit SQLite formats at binding. Null optional clocks
and opaque body/result evidence retain their meaning. Empty or malformed clock
inputs refuse instead of defaulting to the current time.

Project, session, process/work/path claim and strategy execution seed helpers
bind native SQL clock facts. Deterministic strategy and machine-QA seed clocks
are parsed once at their declared owners; release/end absence remains null.
Minimal explicit SQLite machine fixtures format through the shared SQL adapter.

Session keepalive writes bind native expiry facts at the SQL owner. Current
clock ingress uses strict None-only defaults; malformed clocks refuse before
updates. Native inclusive expiry retains microsecond order, while the existing
status projection formats fixed-six UTC and release clears expiry to null.

Peer broker reservations, settlement and native relay adoption retain aware
instants through their owners and adapt only at SQL bindings. Snapshot clocks
compare by instant rather than timezone spelling; malformed clocks refuse.
Lease expiry is inclusive and relay freshness is strict at microsecond precision.
Adoption retains the single wake charge and original message bytes and digests.

Wake receipt and probe expiry, deferred-wake backoff and steering-recipient
cancellation bind native SQL instants. Stale-alive probing selects its latest
activity as a native instant and retains the strict threshold. Native turn-end
reports carry native posture/record clocks, formatting only declared observation
JSON clocks; absent stored observation clocks stay null. Codex rollout readers parse qualified foreign observation clocks into native instants and skip missing or invalid clocks; the relay report owner emits fixed-six UTC without rewriting rollout bytes or vendor evidence. Wake refusal facts and new
steering digests format their declared clocks while retaining opaque bodies.

Recipient wake_after is an instant deadline, declared TIMESTAMPTZ at birth and
included in the same governed stored-instant conversion as receipt clocks.
The classified scalar roster now covers 267 columns across 126 tables; stored
mutable document clocks remain separately owned finite fields. Disposable
SQLite broker seeds write canonical clocks so native-claim snapshot comparisons
exercise the current boundary rather than historical whole-second seed text.

Denial completion and first-prompt hook callers pass native generated clocks to
their existing durable writers. PostgreSQL bindings retain microseconds and the
existing once-only/no-activity-bump rules; malformed generators leave durable
rows unchanged through the existing best-effort hook path. Process-report
arrival uses strict None-only ingress before reading observations, while public
process evidence formats its declared clocks and retains opaque identity text.

Session lifecycle, claim and inventory HTTP routes apply the shared native-only
wire adapter to domain results at JSONResponse construction. Native session
and claim facts remain unchanged internally; owned output clocks become
fixed-six UTC, null clocks remain null, and opaque envelope strings and keys
retain their exact values. Native minimal fixtures exercise the actual API
registration/end routes rather than masking this boundary with text columns.

Released holding groups select their newest occurrence with exact instant
comparison, retain earlier-arrival ties and counts, and order null absence
before dated occurrences, including instants before the Unix epoch.

## Related

- [Instant encoding](encoding.md)
- [Clock verification](verification.md)
- [Timestamp integration owners](ownership-integrations.md)
- [Timestamp verification owners](ownership-verification.md)
