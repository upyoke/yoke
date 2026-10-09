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
