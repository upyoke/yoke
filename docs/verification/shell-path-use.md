# Verify shell operand authority

Use `lint_shell_path_use.analyze_shell_path_use` and
`lint_payload_path_use.extract_payload_path_uses` for the shared shell and
embedded-payload classification. Capacity, content reads, local mutations,
remote resources and unknown operands retain separate authority. A capacity
exemption applies only to that operand, never another use of the same path.

Relative writes resolve from the executing command's cwd, supported leading
`cd`, and canonical client home. Opaque destinations and mid-command directory
changes keep restrictive handling. Unresolved home refuses as
`unresolved_executing_machine_home`: restore canonical client-home metadata or
use an absolute path on the executing machine. Capacity globs retain ordinary
traversal authority. Extend the existing analysis rather than adding a parser,
registry or broad metadata exemption.

Regression sources:

- [Classifier tests](../../runtime/api/domain/test_shell_path_use.py).
- [Authority tests](../../runtime/api/domain/test_shell_path_use_authority.py).
- [Minimized real inputs](../../runtime/api/domain/fixtures/shell_path_use_calls.json).
- [Collection and comparison matrix](../../runtime/api/domain/fixtures/shell_path_use_coverage.json).

The tests cover quoting, compound mutation, unknown syntax, remote argv with
local redirects, embedded Python writes, protected reads/traversal, foreign
lanes, pre-implementation writes and client-home authority across harnesses.
Fail-open is an assertion failure. Keep guard verdict separate from process
exit, and mark missing authority evidence inconclusive.

Historical sampling, replay identity and limitations live in
[the decision record](../archive/decisions/shell-operand-authority.md).
