# Shell operand authority: decision and regression evidence

Shell path analysis composes the existing splitter, operand resolver, write
analysis and remote-resource rules. It retains capacity, filesystem-read,
local-mutation, remote-resource and unknown roles. Capacity authority is local
to an operand: another use of that path never receives that exemption.
Relative writes reuse command execution cwd, including supported leading
`cd` statements and the executing client's home. Opaque syntax remains
governed. This adds no shell interpreter, policy setting or command registry.

## Collection and limits

The frozen UTC interval is **2026-09-24T16:32:33Z inclusive through
2026-10-08T16:32:33Z exclusive**. Collection used registered `yoke db read`
calls after live column/index discovery. The event-name/created-at index and
primary-key keyset pagination bounded event reads; tool-call reads used a
verified lower id bound plus exact timestamps. An indexed audit found zero
window records below that bound. Each page was limited to 100 rows and checked
for truncation. Query text, request identities, counts and comparisons are in
[`shell_path_use_coverage.json`](../../../runtime/api/domain/fixtures/shell_path_use_coverage.json).

The retained population contained 148,527 tool records. Bash had 135,315
completed executions, 2,125 execution failures and 877 guard-denied records;
pending/interrupted/structured-exit and other tools were separately retained
in the population capture, not treated as permissions. There were 898 denied
records with unknown tool name, illustrating why Bash-name filtering alone
does not enumerate refusals.

All 539 retained relevant guard events were collected: 199 canonical
source-main denials, 180 canonical session-cwd denials, 16 privacy advisories,
118 legacy session-cwd blocks and 26 legacy foreign-lane warnings. Legacy and
canonical rows can describe the same evaluation; 539 is an event count, not
a count of distinct refused commands. Privacy advisories accompanied 11
completed executions, four execution failures and one denial by another guard.
Indexed checks retained no named fail-open, read-only mismatch exception,
source-main escape or path-claim-denial events in this interval. Suppression
has no dedicated durable event in the examined parser path. These absences
prove neither absence of the behavior nor permission.

The permitted/execution-failed sample selected the newest call in each
populated outcome × harness × command-family × shell-shape stratum: 75 calls.
Families were capacity, remote, reader, Git, writer, Python, adapter and other;
shapes were simple, compound and redirected. The bounded summary was used
only for sample selection. It is limited to 500 characters and was never
replayed as an invocation. Claim context was reconstructed after selection;
historical claim-context strata are incomplete, not an asserted random sample.

Of 223 selected sessions, transcripts were accessible for 133 Codex and 57
Claude sessions. Four Codex, 23 Claude and six Cursor transcripts were
unavailable under the bounded lookup. Earlier-started sessions and missing
native archives remain exclusions; no home-wide search was performed.
Full native inputs were recovered for 147 calls, including 39 of the 75
sampled executions: 96 denied, 32 completed and 19 execution-failed. Claude
joins use exact native tool-use identity. Codex joins use unique literal call
input, bounded timestamp/summary correlation or matching native refusal
evidence; the matrix records each basis. Ambiguous joins were excluded.

Available tool retention began at 2026-09-10T00:00:07.129Z. The original
capacity refusal recorded client guard revision
`fc87078b9e30367920d2df847e4b4ed061860c4c` and serving guard revision
`b300908f421f9be833eb88797b5ebb776148ebbd`; native Codex was 0.161.0.
The installed CLI reported `source`, not a release number. Baseline replay
uses exact source `9487e7d4b3f50dcaefbd442a9caf27580ee85c0e`, not an invented
match to either serving revision. Candidate identity is the committed tree
recorded by verification. Earlier native session-start Git metadata is not
execution-time source authority.

## Isolated before/after review

No archived command was executed. Replay imported baseline source into an
isolated module overlay, then evaluated the same full native inputs against
candidate extraction. Planning scratch filtering, authority queries and
emitters were stubbed; no original mutation or remote action was dispatched.
The investigation wrote secure raw captures and its replay program at
`/tmp/yoke-path-evidence-1yl775bl`; committed fixtures contain minimized,
deidentified operands and no native private payloads or credential values.

Claims, lane creation and stage transitions were reconstructed from immutable
timestamps: 95 claims, 90 lanes and 368 transitions were captured. Only the
capacity refusal and its permitted counterpart have sufficient authority
evidence for a guard verdict. The matrix marks the other **145 inconclusive**:
historical effective policies, every occupant and canonical machine fact were
not fully recovered. Their classifier comparisons are evidence, not permission
passes. Warning-to-silent-allow behavior is consequently unproven, not green.

| Actual call | Original guard | Intended authority | Baseline | Candidate |
|---|---|---|---|---|
| 971695: `df -k` against installation directory and `/tmp` | Refused | Permit capacity only | Refused | Permitted |
| 971722: same command against its held lane and `/tmp` | Executed | Permit capacity only | Permitted | Permitted |

The original holder's claim, lane and implementing transition predate both
calls; exact identities and the immutable Dash pin are in the coverage file.
Capacity exposes filesystem totals, not installation contents. Expected
permission was assigned from that access distinction, independently of the
observed refusal.

The comparison changed 36 of 147 classifier projections, all explained in the matrix:
six expose already-resolved variable redirects in the same free temporary
root; ten expose existing relative write positions (including supported
leading-cd resolution); one exposes an existing embedded Python write; two
remove inert heredoc text previously mistaken for absolute paths. Sixteen further projections retain previously missed home-relative read/traversal
operands using executing-machine home. In addition, known state moves carry
their path operands to write consumers,
and Git fetch now receives source-main mutation protection. Unresolved-write
facts, read signatures, path-claim mutations and the established conservative
compound-Git lane judgment remain unchanged. No other guard transition is asserted: missing
historical authority prevents deciding it. Mid-command directory changes and
opaque destinations keep existing conservative handling rather than inferred
access authority.

## Durable checks

Fifteen minimized actual inputs retain independent operand expectations.
Tests derive quoting/normalization, compound mutation, unknown syntax and
remote-argv/local-redirect variations from them. Isolated authority tests
exercise the central hook for Claude, Codex and Cursor; they retain protected
content/traversal, foreign-lane writes, pre-implementation writes, client-home
authority and real embedded Python writes. Fail-open is an assertion failure.
Existing source-main, privacy, parser and adapter suites provide the remaining
guard-chain checks on the committed candidate. The evidence does not claim
exhaustive execution coverage from the sample or recover inaccessible history.

An unresolved executing-machine home operand refuses by name as
`unresolved_executing_machine_home`, with recovery to canonical client-home
metadata or a literal absolute client path. It never becomes a relative path
under the held lane. Capacity operands with glob expansion retain ordinary
authority because expansion can traverse a protected directory.
