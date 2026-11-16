# Native Windows evidence ledger

This ledger records expected behavior, not a Windows support claim. Every
command spelling from `command_tree.command_routes()` has a CLI row in each
native mode: local, self-hosted client and hosted client. CLI here is the
`yoke` shell command surface, independent of the harness that invokes it.
Hook events and desktop behaviors have separate harness surface rows from
the installed-source manifests. WSL results never prove native Windows rows.

`docs/verification/windows-ledger/*.csv` is the checked-in expectation table.
Rows have stable ids derived from operation, surface and mode. The table is
split into bounded hash shards to keep each file within the line limit.
`product_boundary_inventory.py` supplies command boundary metadata; command
routes remain the exhaustive spelling owner. A new route fails the ledger
test until its expected rows are checked in.

Refresh after changing routes or manifest promises, then review the CSV diff:

```text
yoke dev run -- python3 -m runtime.api.tools.windows_evidence refresh --target-root .
yoke dev run -- python3 -m runtime.api.tools.windows_evidence check --target-root .
```

Refresh preserves existing expectations. New rows default to `must-pass`.
Use `expected-refusal` with the exact refusal reason, `not-applicable` with a
reason, or `upstream-limitation` with a reason and a Cursor issue HTTPS link.
An upstream limitation remains a failed operation, never passing proof.
Removing a promised operation removes its row on refresh; historical receipts
remain in the QA store.

For each machine case, set `method_config.windows_ledger_row_ids` to the
nonempty list of rows that the case actually exercises. Persistence copies
these execution-bound ids into `raw_result.evidence.windows_ledger.row_ids`.
The native adapter supplies `evidence.connection` facts: `os=windows`,
`edition`, `build`, `harness_version` (a per-harness version map is accepted),
`yoke_release`, `observed_outcome`, and `reason` for a refusal or N/A.
Case-specific facts in `evidence.windows_ledger` take precedence; row tags
always come from the case configuration. Outcomes are `passed`, `refused`,
`not_applicable`, `upstream_limitation`, or `failed`.

Read every page of durable machine QA receipts through the registered CLI:

```text
yoke dev run -- python3 -m runtime.api.tools.windows_evidence report --target-root . --project yoke --yoke-release RELEASE
```

For offline analysis, pass `--receipts receipts.json` instead of `--project`;
the input is a JSON array of `yoke qa run list --json` result rows. The report
is read-only and emits JSON with the expectation, current state, QA run id,
Windows edition/build, harness version and Yoke release for each operation.
It considers completed receipts for the exact requested release, with native
Windows facts and row tags. The newest matching run id wins, including a
failed rerun. A passing receipt proves `must-pass` only with outcome `passed`;
expected refusals and N/A require their exact declared reason. An expected
N/A without a receipt is still `unproven`. Missing or incomplete evidence is
`unproven`; it is never inferred from events, documentation or another OS.
