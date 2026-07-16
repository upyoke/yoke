"""Operation inventory rows for the GitHub Actions CLI family."""

from __future__ import annotations

from typing import Tuple

from yoke_cli.operation_inventory_model import _Row, _w


WRAPPED_ROWS: Tuple[_Row, ...] = (
    _w("yoke github release create-next-tag", "github_release"),
    _w("yoke github-actions check-ci", "github_actions"),
    _w("yoke github-actions workflow dispatch", "github_actions"),
    _w("yoke github-actions workflow dispatch-once", "github_actions"),
    _w("yoke github-actions workflow find-run", "github_actions"),
    _w("yoke github-actions run jobs-count", "github_actions"),
    _w("yoke github-actions trigger", "github_actions"),
    _w("yoke github-actions trigger-once", "github_actions"),
    _w("yoke github-actions find-run", "github_actions"),
    _w("yoke github-actions poll", "github_actions"),
    _w("yoke github-actions jobs-count", "github_actions"),
    _w("yoke github-actions wait-run", "github_actions"),
    _w("yoke github-actions runners status", "github_actions"),
    # Repo secret/variable writers arm CI and rotate configuration without a
    # host GitHub CLI or a bearer token in the operator shell.
    _w("yoke github-actions secret set", "github_actions"),
    _w("yoke github-actions secret delete", "github_actions"),
    _w("yoke github-actions variable get", "github_actions"),
    _w("yoke github-actions variable set", "github_actions"),
    _w("yoke github-actions variable delete", "github_actions"),
)


__all__ = ["WRAPPED_ROWS"]
