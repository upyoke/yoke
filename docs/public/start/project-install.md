# Project installation

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Get started](index.md) > Project installation
<!-- /yoke:breadcrumbs -->

Install the operating layer in an existing project, and keep source-maintainer
launcher ownership separate from released product commands.

## Project-only install

If the project already exists in the universe and you only need the repo
operating layer:

```bash
yoke project install ~/path/to/checkout
```

That materializes skills, agents, hooks, and `.yoke/docs` from the engine's
public docs corpus.

Check readiness: `yoke doctor run --install --project P`.
Checks cover machine/relay, hook version, unattended permissions, GitHub auth,
CLI sign-in, dashboard build, this session's hook delivery, foreign residue,
guidance versions and instruction discovery. Each failure names its next step.
Intentional GitHub disablement is N/A; unknown evidence cannot pass.
Non-interactive setup shows and saves the result; machine-only runs omit project
checks. Installed hooks need a new harness session to prove actual delivery.
See [Doctor](../operations/doctor.md#doctor) for full checks.

The run finishes the job rather than leaving you a commit to push. It fetches
the branch's remote first and fast-forwards when the checkout is simply
behind, so the layer is generated against current upstream; it commits the
paths it owns; and it pushes that commit. If the remote advanced while the
run was writing, it moves onto the new revision and **regenerates** the layer
there — never a merge, which would keep whichever obsolete generated content
the older side happened to carry.

Where the branch does not accept a direct push, the same commit is pushed to
a `yoke-install/<sha>` branch and proposed as a pull request. Where the push
cannot land at all, the report says `publication_pending` and names the
commit plus the command that finishes it — and the command exits `3` rather
than reporting a clean install the remote never saw.

Two refusals are deliberate. A default branch carrying commits of your own
that the remote lacks is reported instead of pushed, because publishing the
layer is not permission to publish your work-in-progress — and a commit
merely *titled* like an install counts as yours unless its changes stay
inside what the install writes. Files it shares with you rather than owns are
on your side of that line: it merges its hook entries into your
`.claude/settings.json`, appends one line to your `.gitignore`, and writes
into the file-line policy config, so it cannot tell its content there from
yours. A commit it did not just make that touches one of those is reported —
never pushed, and never rewritten while reconciling with the remote. And a
checkout with no remote is a local-only project: publication is skipped, not
failed, as it is for `--no-commit`. Pass `--no-publish` to commit without
pushing.

An unreachable remote does **not** stop the install, which is the one place
it differs from starting other work. Creating a worktree refuses an
unverifiable remote, because new work would have no current revision to
start from; installing writes a local layer, so an offline machine still
gets the thing it asked for. The run records why it could not read the
remote and publication then reports `publication_pending` — you are never
told the remote has a layer it never received.

## Source-maintainer launcher

A source-maintainer launcher also runs the released `yoke-cli` uv tool by
default, using isolated Python so a checkout, active venv or PYTHONPATH cannot
change operator commands. Missing or source-bound tool installs refuse with
`released_cli_unavailable` or `released_cli_required`; rerun [the installer](install.md).
From the registered source main checkout, repair the launcher with
`python3 -m yoke_core.tools.install_yoke_launcher --repair`.
Use `yoke dev run -- <command>` for claimed-lane source checks. Operators can
explicitly choose source code for one command with
`YOKE_SOURCE_DEV=1 YOKE_HOME=/absolute/source/checkout yoke <command>`.
Do not export that opt-in for everyday fleet or steering commands.

## Related

- [Install and onboard](install.md)
- [Get started](index.md)
- [Remove Yoke](uninstall.md)
