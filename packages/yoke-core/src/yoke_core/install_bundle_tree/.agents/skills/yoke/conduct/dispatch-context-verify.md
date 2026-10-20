# Conduct — exhausted Tester fallback

Verify only; never implement. Run the declared test commands on main
(baseline) and the lane; a crashed baseline is UNTRUSTED. Match failures by
test name plus error. PASS only with no new or unmatched failures; an untrusted baseline with
failures, or nothing executed, is never PASS. Else FAIL with captures. Persist via [review-insert](dispatch-context-artifacts.md).
Ownership: `.yoke/docs/agents/rules/verification.md#verification-failure-ownership`;
`.yoke/docs/verification/consumer-proof.md`.
