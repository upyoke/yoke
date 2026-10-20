# Blitz — review and close

Run the full suite, then add to the document:

```markdown
## Blitz Completion

- Completed:
- Changed:
- Remaining:
- Verification identities:
- Parent reconciliation:
```

Walk forward one stage at a time; at a release wait keep the claim and park:

```text
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "Execution document reconciled with passing evidence"
yoke claims work release --item ITEM --reason "Blitz completed"
```
