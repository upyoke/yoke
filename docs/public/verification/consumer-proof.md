# Consumer proof

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Consumer proof
<!-- /yoke:breadcrumbs -->

Consumer compatibility belongs to the configured release-time exact-pair gate.
An item merge needs no separate consumer build or verification-only companion.
Consumer code changes still require a linked companion in that project.

Ordinary producer pull requests and main pushes run producer CI without
starting hosted consumer integration. Automatic consumer checks run only for
release candidates. This reduces Actions consumption and accepts discovering
integration failures later; producer review, QA and merge checks still apply.

## Release proof

Use the project's declared release workflow. Its existing consumer gate builds
against the exact producer candidate and bound consumer commit before the
release publishes its tag. A passing producer suite alone cannot prove that
pair; the release gate owns this evidence and refuses a failed or unproven pair.
With no prior result, the gate dispatches and awaits proof itself. Retries
and simultaneous environment callers join proof for the same immutable pair;
a changed producer or consumer commit needs its own proof. Missing, failed,
cancelled, timed-out or mismatched evidence cannot publish a release.
Do not create per-merge rosters, path policies or consumer-build requirements.

Author acceptance criteria around that existing release gate. Record ordinary
item verification at review and release proof at its delivery boundary; avoid
adding a second consumer-build AC before each item merge. An explicitly
requested consumer test may still name an exact published producer candidate
through its existing workflow inputs; see
[producer candidate inputs](index.md#proving-an-exact-producer-candidate).

## Diagnose a failed pair

Read the failed consumer run and its job. The release refusal must retain the
exact producer and consumer commits, the run URL and a supported recovery.
Producer attribution names the changed commit interval and item references to
inspect. A range is evidence about candidate changes, not a proven single
culprit; compare it with the failing job before assigning the fix.

For a producer regression, correct the producer in its owning item. When the
consumer needs code changes, use its linked companion. Retry the existing
release gate after correcting the failure; a missing or failed proof cannot
be waived by a producer-only green run.

Unavailable history must name that limitation and how to restore it. A release
checkout needs full history and release tags so the interval can be read.
Missing history never proves that no producer item caused a failure.

## Related

- [Verification](index.md)
- [Project scoping](../agents/rules/lanes-and-claims.md#project-scoping)
