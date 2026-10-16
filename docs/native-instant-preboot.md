# Native instant boot boundary

Candidate local merge, close-out and release-driver code runs against the
serving database before its own release boots ordered history. Until
`0070_native_domain_instants` applies,
clock columns can still be TEXT. An aware datetime parameter produces text
such as `2026-10-10 23:07:54.69593+00`. The permanent migration converts it
exactly; the strict RFC3339 decoder does not accept it before conversion.

Establish relevance before decoding historical evidence. For new clocks
that must be read again or combined with stored clocks in SQL before boot, serialize already-aware values
canonically only at a declared live TEXT column. Native columns continue to
take datetime parameters. This is temporary write compatibility, with no
parser fallback or correction of historical data.

Comparison cutoffs declare the stored column too: PostgreSQL cannot compare
a native datetime parameter with a pre-boot TEXT clock. Canonical text is
used only while that declared column is TEXT; native columns keep datetime
parameters. This does not cast or repair historical values or relax decoding.

At the optional storage read sites, exact empty TEXT means absence,
matching ordered history's conversion to NULL: queue marker/receipt/arming
clocks, terminal merged time, composition freeze and refresh completion.
Close-out falls back to qualified commit time when the queue clock is absent.
Candidate selection, observer guards and carried-work SQL apply the same
absence semantics before comparison. Required clocks and all nonempty
clock evidence still require strict decoding.

## Pre-boot clock boundaries

| Path | Clock consumption and treatment |
| --- | --- |
| `items.detail.get` | Projects queue timestamps, item clocks, claims and QA rows without parsing stored strings. |
| `merge_queue_landing_outcome.recorded_landing` → `merge_queue_route` | Keeps the old landing clock raw through candidate coverage. An uncontained candidate proceeds; unverifiable coverage refuses without formatting unrelated evidence. Proved existing landings still use strict formatting. |
| `merge_queue_landing_marker` | Decodes the three stamps only for a retained PR. A replacement clears its predecessor's stamps without decoding them. Same-PR preservation remains strict. |
| `merge_queue_landing_pending.mark_landing_pending` | Strictly decodes a matching PR's retained episode and the returned episode. The declared writer prevents noncanonical TEXT on this replay. |
| `merge_queue_landing_observer` / landing notice | Strictly uses previous observations and arming episodes for recovery and deduplication. A prior landing presence guard does not decode its unused clock. Its writer supplies canonical TEXT. GitHub merge clocks are qualified provider evidence. |
| `merge_queue_landing_record`, public payload and landing wait | Strictly decodes observation/change clocks for freshness. Dataclass ingress remains strict; its own writer supplies canonical TEXT before boot. |
| `merge_queue_landing_refresh.read_refresh` / `record_age_seconds` | Strictly uses sweep/observation clocks for cadence and freshness. The writer supplies canonical TEXT. |
| Close-out / `standalone_item_merge_evidence._merged_at` | Git/CI evidence establishes receipt identity. Empty optional queue/merged TEXT is absence at the read site; `landing_time` falls back to commit time. The terminal already-closed race path strictly reads a present merged clock. Its registered writer supplies canonical TEXT; a prior landing cannot satisfy a correction. |
| Driver attach / heartbeat / release / authority | Strictly parses canonical JSON attachment clocks. Scalar run clocks do not enter these operations. |
| Run pin / execution context / retry | Whole-row pipe projection preserves stored TEXT. Status, flow, stage and lineage reads do not parse clocks. Explicit clock-field reads remain strict. |
| Composition / carried-work metadata | Strictly compares active successors relevant to a requested chain. SQL filters landings by qualified commit-clock windows; only passing rows enter strict attribution. Exact commit evidence remains independent. |
| Containment visibility / `item_finished_times` | Both finished-window queries bind their cutoff for the live type of `item_status_transitions.created_at`. Only relevant recent transition clocks are decoded, strictly. The inclusive cutoff and finished/unfinished semantics remain the same after boot. |
| Lifecycle / `item_status_transitions._record` | The driver can transition an implemented member to release before boot. Its recorder declares the same clock column, supplying canonical TEXT for subsequent finished-window reads and native datetime after boot. |
| Composition freeze / replay | First freeze consumes native `utc_now`. Replay strictly formats its stored freeze clock; the declared writer supplies canonical TEXT. Snapshots use semantic fields and timestamp presence. |
| `qa_seed` | Reads flow, pinned stages and requirement identity; no run clocks are decoded. |
| QA stage result / attempt ordering | `_clock_columns` and completion ingress remain strict. `execution_start` uses actual attempt starts; capture settlement uses creation clocks. New attempt clocks are canonical TEXT before boot. |
| Stage receipt allocate / complete / latest / QA binding | Uses attempt numbers, identity, status and correlation. Creation/completion clocks remain opaque even on replay. No compatibility writer is needed. |
| Run status / stage updates | Driver-written start/completion TEXT is opaque to execution/retry projections and stays native. Stage entry combines its new parameter and stored value in a `CASE`; the declared writer avoids mixing TIMESTAMPTZ and TEXT operands. Repeating the stage preserves its canonical TEXT clock. Ordered history converts these clocks at boot. |

Scoped post-deploy QA, final completion settlement, carrier presentation,
history pagination and portable run projection use clocks as actual evidence
after the delivered engine boots history. They retain strict decoding.

## Temporary declared write set

| Table | Columns | Repeated consumer |
| --- | --- | --- |
| `items` | `merged_at` | Recorded terminal close-out |
| `items` | `merge_queue_enqueued_at`, `merge_queue_landed_at`, `merge_queue_notified_at` | Retained marker, arming recovery and notice bookkeeping |
| `merge_queue_landing_records` | `observed_at`, `changed_at` | Readback and wait freshness |
| `merge_queue_landing_refreshes` | `started_at`, `completed_at` | Sweep/readback freshness |
| `deployment_runs` | `composition_frozen_at` | Idempotent freeze replay |
| `deployment_runs` | `current_stage_entered_at` | Stage-entry `CASE` with the stored clock |
| `qa_runs` | `started_at`, `completed_at`, `created_at` | Ordering, capture settlement and result completion |
| `item_status_transitions` | `created_at` | Transition readback and finished-window SQL comparison cutoffs |

The process cache uses database/server/user connection identity, without a
DSN or credential. One catalog read loads the fourteen declared fields; a
lock prevents duplicate fills. Writes then use cache lookups. Boot clears
the cache, and a change of stage clears it because the preceding execution stage
may have booted history in another process. Repeating the same stage keeps
the cache. Undeclared fields and unsupported
live types refuse.

## Regression proof and removal

The isolated PostgreSQL TEXT fixture covers relevance, superseded/retained
markers, all fourteen declared fields, cache reuse across connections, driver
attachment replay, freeze replay, QA seeding/ordering, queue record/refresh
reads, receipt replay and run update retry reads. It applies the unchanged
ordered migration and proves native datetime parameters after invalidation.
The optional-clock fixture also exercises actual close-out, arming and
observer read/write paths on empty TEXT, plus the native NULL counterpart.

Once applied-history evidence confirms this migration in every live universe,
remove `preboot_instant_parameters`, declared writer arguments and boot/stage
cache invalidations. Keep strict decoders, relevance filtering and permanent
history. Delivery Notes name this cleanup for steering to file after release.

Fleet rehearsal converges each restored copy through
`migration_fleet_preflight.rehearse` and then requires real product readers to
decode the migrated rows; reader refusals fail the gate. It does not replay
candidate release-driver code against the pre-boot schema. The
[fleet contract](public/databases/migration-fleet.md) owns
complete copy custody. The instant census remains read-only diagnostic evidence
and cannot earn a release receipt.
