"""Per-function opt-outs for the shell-quoted-function-payload lint.

Sibling table consumed by the hot path in
:mod:`lint_shell_quoted_function_payload` so the cap-bound primary
module stays under the 350-line authored-file budget.

``NO_CONSUMER_ALLOWANCE_FUNCTIONS`` lists write-shape function ids
whose CLI writes to ambient-cwd targets. For those adapters a pipe-to-
truncator wrap (``2>&1 | tail -30``, ``| head -10``) silently hides
the stderr signal of a wrong-cwd write, so they must DENY uniformly
under shell choreography — the same outcome the upstream ``cd … &&``
branch already produces.
"""

from __future__ import annotations


NO_CONSUMER_ALLOWANCE_FUNCTIONS: frozenset[str] = frozenset({
    "agents.render.run",
})


__all__ = ["NO_CONSUMER_ALLOWANCE_FUNCTIONS"]
