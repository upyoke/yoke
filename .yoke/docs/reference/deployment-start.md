# Deployment start diagnostics

A normal driver start builds its execution context once. Composition completes
and validates membership before the driver reads it, and returns that pass’s
enrolled references. Branch verification and QA seeding use those members.
The driver reuses the context’s containment basis when starting the run.

The executing transition still locks stable membership, validates mutable item
bindings, freezes requirements and intent, verifies the containment digest,
and stamps execution in one transaction. A stale digest rolls that transaction
back. The driver refreshes only the basis and re-attests, with at most three
retries; other refusals stop immediately and name the repair and re-drive step.
`deployment_runs.execution.containment_basis` is the narrow registered read:

```text
yoke deployment-runs execution containment-basis RUN-ID --json
```

Hold the project deploy lock before using it. A serving build below its declared
minimum version refuses by name; use the same-universe owner’s local authority
when driving the control plane’s own upgrade. Ordinary projects use HTTPS.

Coverage resolves member completion flows as a set, with one project/workflow
default resolution per distinct pair. The flow and source record are shared
within a composition operation. Catalog probes share table and column answers
only inside that operation and only for the same connection. Exiting, including
on refusal, discards the scope; no process-global or cross-request cache exists.
Mutable member status/intent is read afresh. Freeze reuses one custody resolution
for both membership and completion-authority checks; unknown custody still refuses.

Completion publishes exact run/member/environment/candidate attribution in the
existing delivery-stamp facts, in the same transaction as the item's done status.
An independently completed member stays delivered even if its siblings or run
later fail or cancel. Dependency and dashboard readers consume this durable
answer. Accepted QA and a preflight stamp alone do not mean the item completed.

The driver raw capture contains `Deployment start timing: ` JSON lines from
preflight pin reading onward. Each step has a UTC start/end timestamp, monotonic
elapsed milliseconds, outcome, run ID, source SHA, member count, and transport.
SHA and member count remain explicitly unset until their authoritative reads.
Pin reading, worktree retirement/ensure, child launch, context substeps, branch
verification, QA seed, containment attestation, freeze, and executing stamp are
named separately. HTTPS returns server substeps with its response for the driver
to flush; local execution collects them through the same contract. The watcher
preserves preflight lines when it appends child output. Records carry no secrets,
require no telemetry table, and are never operational authority.

For a start-gap measurement, subtract the earliest preflight-start timestamp
from the successful executing-transition end (both on the driver’s clock) in that same run’s raw capture. Report
the sum of context elapsed time, freeze elapsed time, and any refresh attempts
alongside the total. Compare matched source/transport/member-count conditions;
missing markers are incomplete evidence, never a zero-time result.

The read-only report can locate the run’s raw capture on its driver machine:

```text
python3 -m yoke_core.tools.deployment_start_report --run-id RUN-ID --baseline-seconds SECONDS
```

Pass `--capture PATH` for an exported raw capture. The report refuses incomplete
markers or more than one context build, and prints the measured total and every
step’s elapsed time; a slower start still reports its measured difference.
