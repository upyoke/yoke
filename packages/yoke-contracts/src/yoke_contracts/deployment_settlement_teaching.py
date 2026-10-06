"""CLI teaching for completing a deployment run through settlement."""

from __future__ import annotations

UPDATE_DESCRIPTION = """\
Set one deployment-run field. `status succeeded` settles the run first: every
final member this run must close closes in one commit, or none does and the
run stays executing and settling with each blocker named. A run settles on
its own target environment. A member whose only open post-deploy obligations
target another environment (stage QA beside a production release) does not
hold the run: it is stamped deployed_to, stays at its release wait, and
closes when a run on that environment accepts its obligation. A member red
or unanswered on this run's own target still holds it. Re-drive a settling
run under the project deploy lock with the same command."""
