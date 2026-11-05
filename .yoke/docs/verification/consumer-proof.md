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
The hosted deploy driver starts or joins the bound pair before waiting for
producer CI, without waiting for the proof verdict. It uses the run owner's
existing GitHub authority; no push workflow credential is added. The bridge
still decides publication and joins the same pair. An early-start failure names
its recovery and the bridge retries dispatch before publication. If the bound
consumer later moves, the early proof is wasted but harmless: another pair
needs its own proof. With no prior result, the gate dispatches and awaits proof itself. Retries
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

## Explicit Yoke repository proof

**Yoke source repo only:** from a claimed source lane, dispatch a requested pair with:

```text
yoke dev run -- python3 -m runtime.api.tools.platform_consumer_dispatch --candidate-sha FULL_YOKE_SHA --consumer-sha FULL_PLATFORM_SHA # Yoke source repo only
```

Use full 40-hex commits and the authenticated connection that owns Platform.
This entry point ensures the immutable consumer tag and uses the release
helper's exact dispatch builder: ref, both `product_ref` and `consumer_sha`
inputs, request id, correlation input and project. Do not assemble a trigger
command by hand. The release joins the same pair's run; another pair uses
another request id, and changing a payload under a reused id still refuses
with `idempotency_key_collision`. A pending dispatch names its retry recovery;
repeat this command with the same pair to join it.

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
