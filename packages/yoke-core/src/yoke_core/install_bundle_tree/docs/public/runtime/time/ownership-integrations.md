# Timestamp integration owners

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Runtime](../index.md) > Integration owners
<!-- /yoke:breadcrumbs -->

Read the native clock writers and explicit wire boundaries for identity and external integrations.

## Identity, provider and integration clocks

Invites retain native creation and acceptance instants; list projections format
those declared fields as fixed-six UTC/null. Organization seed, external identity
link, visitor link/refusal and release-note writes use the shared native SQL adapter. Release-note
pipe output formats only its creation clock; its default version remains a UTC
calendar date. Role and permission seeding also binds native creation clocks.
GitHub binding and installation payloads format only verification/sync clocks
as fixed-six UTC/null, preserving opaque repository and account identities.

Release build metadata validates its supplied clock before replacing output,
and emits fixed-six UTC. Relay installation/failure receipts and API JSON logs
share the canonical formatter. Board timing retains native wall instants and
formats its declared event clocks before emission; durations remain monotonic.

Org and project role grants bind native clocks. Strategy section CAS, cached
render headers and staleness checks compare instants. Board calendar buckets
project native instants to UTC dates; age windows use aware timestamps.

Local and self-host universe import authority/credential writes bind native
clocks. New archive freeze and source-authority receipts format fixed-six UTC;
archive contents and existing receipt bytes retain their custody. Resume notices,
path override envelopes and capacity/performance report clocks use the shared
formatter at their owned JSON boundary. Opaque identifiers remain unchanged.

Dispatcher request JSON projects native payload, precondition and option clocks while Python-mode values retain datetimes. New result digests and public/CLI payloads apply the shared native
clock JSON projection, preserving opaque strings, integers and existing receipt
bytes. Release-build and artifact models retain native generation clocks until JSON output; direct materialization validates before output changes. Newly authored distribution channel pointers format generated_at as fixed-six UTC and refuse invalid input before replacing output; existing pointer bytes and content digests remain unchanged. Native spawn results retain aware start clocks until evidence output; capture and custody formats remain owned file boundaries. Relay adapter launch deadlines project fixed-six UTC or null and refuse malformed clocks. Newly minted Cursor trust clocks preserve microseconds through the shared UTC formatter; existing trust-file bytes remain untouched. Current board and session-message fixtures declare native clock columns;
calendar-day rollups remain dates. Git epoch seconds stay a provider protocol,
with fixed-six UTC formatting when projected into a request. Provider seconds/millisecond reset adapters retain fixed-six microseconds and preserve optional null on invalid or out-of-range epochs.

GitHub token facts retain native aware issued/expiry instants through authorization and GraphQL refresh telemetry; explicit numeric token ages and JWT seconds remain duration/protocol fields. Qualified provider clocks use shared strict ingress. Actions wait-run projects only its owned updated_at to fixed-six UTC or null, and stall decisions retain native precision without guessing naive or malformed clocks. Actions run selection keeps run/attempt priority, compares native created instants, then uses ids; absent clocks sort before dated facts and provider payloads retain their original encodings.

Project registration, structure writes, infrastructure creation, capability repair/seed/secret metadata and GitHub sync receipts bind native SQL instants. GitHub installation and repository binding helpers accept native verification facts and adapt at each backend binding. Project retirement retains a native nullable fact, compares instants on repeat calls and explicitly formats its event context clock.

GitHub credential refresh/access timing retains native aware instants internally and strict shared ingress rejects naive clocks. Document reads parse only declared refresh and cached-access expiry fields; new file writes format those fields as fixed-six UTC, while unrelated evidence is opaque and reads preserve bytes. The existing immutable standalone helper bundle now includes exact shared-kernel bytes, keeping portable execution independent of product imports.

Named entry ingress forwards native default and supplied qualified instants;
blank or malformed supplied clocks refuse before the entry writer. Governed
exception audit fingerprints bind native start/completion clocks through the
shared adapter, retaining explicit backup/no-backup authority requirements.

Governed apply/rehearsal helpers retain Native audit and result clocks; rehearsal/adoption result constructors refuse internal wire/naive clocks and preserve nullable rehearsal absence. Both
audit writer surfaces use one finite parameter owner; native update clocks keep
nullable absence and reject malformed values before mutation. New verification
command outcomes and console projections format their declared clocks as
fixed-six UTC. Current migration capability/audit fixtures declare native types.

Compact GitHub mirror flags create native instants and adapt only at SQL binding;
full-body synchronization clears the clock to null. Invalid generated clocks
refuse before the best-effort savepoint. Severity initialization shares the same
SQL adapter, retaining native PostgreSQL facts and canonical SQLite boundary
clocks without changing the existing conflict-preserving seed behavior.

Bound-release and persistent-release fixture callers parse their deterministic
project seed clocks before invoking the native project SQL owner. Shared
cross-project release clocks stay native through site/environment seeding;
consumer authorization and bound-pin diagnoses keep their existing semantics.

Attribution fixtures generate native freshness clocks, strictly parse supplied
current/recent item instants and bind deterministic item clocks natively.
Absent attribution clocks remain null; explicit SQLite bindings format canonical
fixed-six UTC while item/session identifiers retain opaque values.

Project identity test writers parse the finite stored-clock roster before schema
lookup and bind native values through the shared SQL parameter adapter. The
actual git Doctor schema owners declare those clocks as `TIMESTAMPTZ`. Their
fixture tests cover supplied-clock refusal, microseconds across server time
zones, nullable clocks, opaque text, and explicit canonical SQLite binding.

The webapp scaffold successor reuses the byte-identical shared Python kernel.
Sessions parse expiry before native microsecond comparison; creation and expiry
are formatted only at SQLite binds. Task starts are native instants, while task
duration, retention and HTTP timing use monotonic clocks. New SQLite membership
and adoption evidence binds fixed-six clocks explicitly without rewriting old
immutable evidence or changing its exact append-only guard shape. Its appended
application migration validates all five finite columns and schema dependencies
before one atomic four-table rebuild with preserved keys, checks and nullability.
Boot retains the WAL restore point and resolves its serving floor from the
applying artifact; customized dependencies require project-owned migration work.


## Related

- [Instant encoding](encoding.md)
- [Clock verification](verification.md)
- [Timestamp owners](ownership.md)
- [Timestamp verification owners](ownership-verification.md)
