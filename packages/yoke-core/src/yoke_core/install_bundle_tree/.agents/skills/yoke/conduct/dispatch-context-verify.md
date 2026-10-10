# Conduct — exhausted Tester verification

Only after initial Tester plus every output retry returns no parseable verdict.
This is the explicit Thin Conduct exception; it permits verification, never
implementation or direct integration simulation. Log entry and field-note first.

Use declared project/spec QA/test commands; if absent, inspect changed test paths
and execute the appropriate registered test surface, not guessed shell scripts.
Respect source-dev wrapper, admission, CI and owning continuation rules. A full
QA execution is not duplicated as an exploratory sweep.

## Baseline trust

Locate the actual main checkout through git worktree list, verifying its branch
is main; do not switch/reset the task lane. A git-common-dir fallback is only a
candidate path and must pass the same branch check. Resolve exact baseline head.
Capture each named baseline command with tool/runtime/source identity and test
name, assertion/error and file:line. No GNU timeout or interpolated sh -c.

```text
git -C {MAIN_ROOT} worktree list --porcelain
git -C {BASELINE_CHECKOUT} branch --show-current
git -C {BASELINE_CHECKOUT} rev-parse HEAD
```

Missing checkout/tool, runner crash, unparseable/empty expected output or harness
error makes BASELINE_TRUST=UNTRUSTED with reason. A product test failure alone
does not invalidate captured baseline evidence. Baseline commands need the same
declared validation environment, not production control-plane mutation.

## Branch evidence and ownership

Run actual claimed candidate checks with capture-first or their watcher. Preserve
exit and printed capture; never pipe tests to head/tail. Compare failures by
test name PLUS error or location; same name/different signature is indeterminate.
Record new, signature-matched, indeterminate and harness failures separately.
Green trusted baseline means every branch failure is new.

Classification is diagnostic, not a waiver. Current-item failures remain this
item's responsibility, including future/planned ownership of a touched file.
Widen/reconcile claims and dependencies before fixing; operator override only
for irreducible live collision with explicit approval. No green claim by pointing
at future work or an old baseline. A permitted live conflict/explicit waiver
names its evidence and remaining obligation.

## Durable verdict

Trusted, signature-matched baseline failures alone permit a task review PASS
when the task introduces no new failure and has no indeterminate/harness result.
Preserve those captures and classify the PASS as baseline-only. This review
classification does not turn a failing registered item gate green: every
current-item verification failure still gets resolved within this item before
its final gate, unless the documented live conflict/operator waiver applies.

PASS requires successful required commands and no unresolved owned product,
indeterminate or harness failures. Untrusted baseline plus failures prohibits
PASS; empty/unexecuted checks are inconclusive, never pass. Red checks return
FAIL with feedback and exact captures for Engineer retry. Record baseline trust
and comparison reason alongside the synthetic verdict, then persist the exact
task's attributed review through its native review-insert gate.

Log Ouroboros: Tester output exhausted, direct verification required, actual
outcome and suspected context/dispatch cause. Continue the owning closeout;
never end with only a local verdict or convert pending evidence into acceptance.
