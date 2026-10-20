# /yoke implement — evidence-only items

If done or usher hits the empty-branch guard (exit 8): roll back to
`implemented`, acquire the claim, and confirm
`git -C <lane> status --porcelain --untracked-files=all` prints nothing.
Then release the lane and rerun:

```text
yoke item-worktrees release PREFIX-N --all-active --reason evidence-only-recovery
```
