# Clock verification and recovery

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Runtime](../index.md) > Clock verification
<!-- /yoke:breadcrumbs -->

Validate supplied clocks before acting, retain exact deadlines and preserve governed conversion evidence.

## Qualified input and historical conversion

Supplied inputs require a valid calendar and an explicit UTC offset. Naive
datetimes, date-only values, unknown `-00:00` offsets and precision beyond
microseconds refuse as `invalid_instant`; supply a qualified instant instead.
Offset-qualified inputs normalize to the same UTC instant without dropping
microseconds. UTC conversion outside years 1 through 9999 also refuses.
The runtime parser never guesses a timezone or repairs history.

One-time governed conversion is frozen in migration history alongside its column roster, storage converter and finite document helpers. The entry loads these
helpers through explicit sibling paths, so installed runners can load candidate history without importing candidate runtime packages. Governed rehearsal uses
the project's declared authority and a separately bound validation copy. The native cutover's source-maintainer launcher procedure lives in the source
development guide. `stored_instant_conversion` remains the source helper for separate declared
storage conversions. It checks all source columns before changing types and combines each table's alterations into one rewrite. Approved historical calendar
values assume UTC; optional blanks become NULL, and specifically approved owner-creation repairs replace missing item updates or malformed Ouroboros
observations. These are explicit historical assumptions, not recovered facts or future input fallbacks. The caller retains the restore point, transaction,
serving floor and receipts; append-only UPDATE/DELETE guards remain enabled during type conversion.
Permanent history freezes all 267 columns across 126 tables. Excess historical
fraction digits are dropped at microseconds. Its finite mutable-document policy
repairs only declared usage, episode, resume-notice, driver, QA-wait and
machine-decision clocks using existing owner facts, preserving other document
fields. Unknown optional usage observations become JSON null. Repairs use
compare-and-set predicates; a concurrent writer refuses instead of losing newer
facts. All document repairs are prepared before any type change. The owned
progress view is reconstructed inside the same transaction; stored relay
plan/model observations, plan reset clocks, capacity observations and health
failure/quarantine/refusal clocks follow finite owned paths. Optional unknowns
become null; invalid supplied history uses the relay observation owner fact.
Model retirement calendar labels and opaque fields retain their meaning.
Unowned dependents or custom view metadata refuse before any view is dropped. No immutable or signed document is rewritten.
Live relay health stores an absent failure or refusal as an empty object, so fleet preflight retires this entry's standing document invariant (it wanted null clock keys).
The serving catalog probe also checks declared native instant types: matching
column names with TEXT or timestamp-without-zone storage cannot prove that a
build requiring TIMESTAMPTZ can serve that database. The governed serving floor
remains an independent requirement.

The strict instant formatter requires a supplied instant. A nullable view field
preserves null before formatting; absence cannot be passed through the parser
or formatter as if it named a clock. Settlement authority reads a native marker
and tests nullness, including before its additive column has converged.

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
Session usage and machine-capacity readings require Native observation clocks internally; result constructors and capacity probes refuse wire/naive clocks. Shared level placement, launch eligibility and lane-capacity helpers also require Native reference clocks and refuse invalid input before SQL; exhausted-pool refusal text reuses the owned UTC/null reset projection; stored relay JSON observations decode at their owner.
Their owned JSON ingress parses clocks and output formats only declared leaves. Missing usage observations are null.
Carried usage storage canonicalizes its observation while preserving unrelated
JSON facts; malformed clocks refuse before SQL or capacity probes.

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

Notice, messaging, settlement, signing, export-name and fleet polling owners validate supplied clocks before reads
or actions; only null selects the shared clock. Qualified offsets normalize without losing microseconds. Captured
hook endpoints retain their timing owner. Scheduler fixtures declare native columns. QA wakes, parked ordering, hook
context and event relative bounds reuse this clock.

Source-authority receipts format metadata as fixed-six UTC/null and compare native freeze
watermarks before hashing. Private CONNECT-fence birth uses native freeze/retirement columns;
clocks validate before SQL. Credential files and archive diagnostics format owned clocks.
Existing receipt files, frozen fixture IDs and physical PostgreSQL row checksums retain bytes.
Generated board last-synced markers use fixed-six UTC in both CLI and engine paths.


## Related

- [Instant encoding](encoding.md)
- [Timestamp owners](ownership.md)
- [Verification owners](ownership-verification.md)
