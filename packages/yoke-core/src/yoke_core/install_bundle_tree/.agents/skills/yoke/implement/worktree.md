# Implement — lane refusals

Surface the refusal; never force or widen past it. Retry after the fix.

- Claim conflict: coordinate with the holder.
- `upstream-unverified`: restore remote access.
- `upstream-stale`: the owner reconciles; never reset or rebase local commits.
- Dirty main: the holder commits or stashes; never discard.

With `physical_cwd_mode=static`, use absolute lane paths and `git -C`.
`--no-worktree` needs explicit operator request.
