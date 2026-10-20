# /yoke implement — review and handoff

1. Enter the review stage; keep the claim.
2. Review against the spec and every AC; fix, commit, rerun stale QA.
3. Transition one stage at a time to the through-stage:

```text
yoke qa gate-summary --item PREFIX-N --target <handoff-stage>
yoke lifecycle transition PREFIX-N --from <live-stage> --to <next-stage> --reason "Implementation review"
```

4. If a steering seat must act, `yoke say --steering` first. Only after
   the handoff succeeds:

```text
yoke claims work release --item PREFIX-N --reason implementation-handoff
```

5. Reread the pin; report `next_skill_id`. That skill takes its own claim.
