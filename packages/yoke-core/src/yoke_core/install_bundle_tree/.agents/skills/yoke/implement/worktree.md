# Implement — lane refusals

Surface the refusal; never force or widen past it. Retry after the fix.

- Claim conflict: coordinate with the holder.
- `upstream-unverified`: restore remote access.
- `upstream-stale`: the checkout's base branch diverged from origin; its owner reconciles it.
  Never reset or rebase that branch's local commits. Your lane is separate:
  `yoke watch pytest --impacted main` brings it current with origin on each run.
- Dirty main: the holder commits or stashes; never discard.

With `physical_cwd_mode=static`, use absolute lane paths and `git -C`.
`--no-worktree` needs explicit operator request.
