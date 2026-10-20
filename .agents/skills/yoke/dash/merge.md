# Dash — merge

HEAD must match every verdict. Run the printed command once:

```text
yoke watch merge --print-streaming-pair merge-item -- ITEM --wait --result "<result>" --verification "<proof>"
```

- Relay-launched: arm, report the PR, stop.
- Exit 0 is not done; read `[close-out]`.
- Budget exhausted or candidate review pending: checkpoint, park, report, keep the claim.
- Correction: `yoke github merge-queue hold ITEM --json` first.

Next: [close-out](close-out.md).
