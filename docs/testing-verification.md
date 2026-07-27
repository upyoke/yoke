# Testing and Verification

Yoke presents QA as test plans, methods, capabilities, and readable outcomes.
Requirements, runs, and artifacts remain execution records created by Yoke and
its harnesses.

## Methods

A method is the registered contract for one kind of proof: executor, optional
capability kind, verdict path, evidence contract, and success policy. The
built-in roster is:

- **Command** — deterministic worktree command; exit 0 passes and captured
  output is evidence.
- **Browser check** — browser assertions with an automatic verdict.
- **Browser inspection** — screenshots judged against the expected outcome.

The `machine-qa` Pack adds **Terminal check**, **Terminal inspection**, and
**Machine state check**. Those methods share the registered `host_control`
executor and a serial `test-machine` capability.

Inspect the roster and a method contract with:

```text
yoke qa method list --project <project>
yoke qa method get <method-id> --project <project>
```

Built-in, Pack-registered, and project-local sources remain distinct. A method
selects registered code; case instructions never become an executor.

## Test plans

A test plan is a named, project-scoped, ordered sequence of cases. Every case
has a stable slug key, its own method, instructions, and expected outcome, so
one plan may mix command, browser, terminal, and machine proof.

```text
yoke qa plan create <slug> --project <project> --name "<name>"
yoke qa plan edit <slug>
yoke qa plan get <id> --project <project>
```

`qa plan edit` resolves project context from `--project`, then `YOKE_PROJECT`,
then the machine-config checkout mapping. It opens a clean JSON authoring
document in `$VISUAL`, `$EDITOR`, or `vi` and compare-and-swap saves plan
metadata plus the complete ordered case set. Invalid JSON, an editor failure,
or a concurrent edit preserves the temporary document and refuses the write.
An unchanged document preserves the plan timestamp and its case row identities.
The lower-level `qa plan-cases replace` adapter remains available for callers
that already hold a numeric plan id and intentionally replace cases only.

Attach a reusable plan as a project default for one workflow transition:

```text
yoke qa project-default set \
  --project <project> --plan-id <id> \
  --workflow <workflow> --transition <stage>
```

Or attach it to one item:

```text
yoke qa item-plan attach \
  --item <PREFIX-N> --project <project> --plan-id <id> \
  --transition <stage>
```

At the declared transition, Yoke materializes one requirement per case.
Those rows are the snapshot: later plan edits affect only items that have not
materialized the plan. Once any requirement for a plan and transition exists,
the whole plan is considered snapshotted for that item; newly authored cases
do not leak into that item on a later materialization call. Empty plans cannot
be attached or materialized. v1 accepts only the `all-pass` policy, including
case-level overrides, and project-local methods can only be used by plans in
that same project. Case rerun and waiver stay case-scoped, and the transition
consumes the union of all materialized outcomes.

## Capabilities and secrets

A capability is the configured resource a method may need. Its availability
is one of: not configured, configured (unverified), ready, in use, or error.
Serial resources queue while in use; that does not prevent plan attachment.

The Test Mac is one `test-machine` capability, not three separate resources.
Inspect, update non-secret settings, and verify it with:

```text
yoke test-machine get --project <project> --json
yoke test-machine settings-replace \
  --project <project> --settings-file <settings.json> \
  (--new | --base '<as-read-json>')
yoke test-machine verify --project <project>
```

Provision the host once before saving the capability:

1. Create a dedicated macOS test user and make the host reachable through a
   private network.
2. Enable **System Settings → General → Sharing → Remote Login** for that user,
   install the operator public key in `~/.ssh/authorized_keys`, and verify a
   batch SSH login. Do not expose SSH with router port forwarding.
3. Install `tmux`, which `host_control` uses to retain the real terminal
   session while driving and capturing it.
4. In **System Settings → Privacy & Security**, grant the logged-in
   Terminal.app Automation access to Terminal and Screen Recording access.
   Keep the Mac logged in and unlocked for screenshots. These are interactive
   macOS permission grants on the host, not credentials or tokens that Yoke
   stores.
5. Disable automatic system and display sleep for the test interval. Restore
   the operator's normal sleep policy when the dedicated test interval ends.

The saved settings document contains exactly `resource_name`, `host`, `user`,
and `operating_notes`. It contains no credentials. `ssh_private_key` is the
only Test Mac credential. Store it on the machine that runs `host_control`:

```text
printf '%s' "$SSH_PRIVATE_KEY" | yoke projects capability secret set \
  --project <project> --cap-type test-machine \
  --key ssh_private_key --value-stdin
```

The private key value is the key material, not a path. Yoke writes it to a
capability-owned machine-local file with restricted permissions. Do not copy
it to the remote host, the project checkout, or control-plane settings. Host
baselines run as the dedicated test user and do not invoke `sudo`; no sudo
credential is required. After provisioning or changing any setting, SSH key,
or required macOS permission, run `yoke test-machine verify`; the capability
is not ready until connectivity and terminal-control checks pass.

Secret values never belong in settings JSON, workflow definitions, item
bodies, prompts, logs, captures, or artifacts. The executor receives resolved
secrets only for its subprocess and must redact them from evidence.

## Evidence

The QA screen renders case outcomes and artifacts through the registered
artifact read surface. Durable handles use authorized short-lived downloads;
machine-local handles render on the owning machine and appear elsewhere as an
explicit on-machine or not-portable state.

```text
yoke qa activity list --project <project>
yoke qa artifact read --requirement-id <id> --artifact-id <id>
```

Missing or blocked evidence is never a silent pass. Machine baselines run as
registered operations inside the capability lease, verify the exact
branch-determining host state, and block dependent cases if the baseline cannot
be reached or verified.

## Source verification recipes

Ruff is a locked development dependency. Lint every changed Python path with:

```bash
uv run --frozen ruff check <changed Python paths>
```

Do not call a checkout-local `.venv/bin/ruff` path or rely on an ambient
Homebrew install.

For a changed-test fallback, first list candidates with:

```bash
git diff --name-only --diff-filter=ACMR <base>...HEAD \
  -- ':(glob)**/test_*.py' ':(glob)**/*_test.py'
```

Review the newline-delimited output, then pass the exact existing paths to
`watch_pytest`. Do not pipe NUL-delimited Git output through `rg -z`, and never
feed a filter diagnostic to pytest as a filename.
