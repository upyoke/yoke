# /yoke implement — review loop and handoff

Start after implementation and recorded AC verification, or resume at the
pinned review stage. [Test and record](implementing/test-and-record.md) owns
the complete QA roster. Review every requirement, not merely test output.

Before each transition, commit all fixes/new files, then refresh affected
cases against that committed tree. Materialize the target transition's plans
and execute unsatisfied cases. Browser proof must serve the expected branch
and SHA; a capture without an accepted verdict is insufficient.
Run the blocking stale-string verify through the project's source-dev
authority before the commit. Failures must be repaired and rerun.

Use `lifecycle.transition.execute` for the pinned adjacent stage:

```text
yoke lifecycle transition PREFIX-N --from <live-stage> --to <next-stage> --reason "Implementation review"
```

1. Enter the review stage without releasing the claim.
2. Review the branch against spec and every AC. Fix in the same lane,
   commit, refresh affected QA and continue.
3. When review passes, transition to this binding's through-stage.
   Only after success release the claim:

```text
yoke claims work release --item PREFIX-N --reason implementation-handoff
```

Never jump past the through-stage or substitute scalar status writes.
A suite pass does not satisfy the union gate; preview the actual target with
`yoke qa gate-summary --item PREFIX-N --target <handoff-stage>`.
Report tests as tests until the gated transition succeeds.

## Fresh handoff

Read `yoke workflows item get PREFIX-N` again. Report the actual review and
handoff stages and returned `next_skill_id`. Stop this skill at its boundary;
when the mandate authorizes further delivery, invoke that fresh bound skill,
which acquires its own claim. Never infer its route from memory.

When a covering steering seat must act, send `yoke say --steering` before
releasing a still-held claim. After release the address uses the item last
held. Ending a turn sends no Fleet message.
