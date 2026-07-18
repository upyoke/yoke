"""Deployment command rows for the operation inventory."""

from __future__ import annotations

from typing import Tuple

from yoke_cli.operation_inventory_model import _Row, _w


WRAPPED_ROWS: Tuple[_Row, ...] = (
    _w("yoke deployment-flows get", "deployment_flows"),
    _w("yoke deployment-flows reconcile-project", "deployment_flows"),
    _w("yoke deployment-flows set-status", "deployment_flows"),
    _w("yoke deployment-flows stages", "deployment_flows"),
    _w("yoke deployment-flows update-stages", "deployment_flows"),
    _w("yoke deployment-runs create", "deployment_runs"),
    _w("yoke deployment-runs start-for-item", "deployment_runs"),
    _w("yoke deployment-runs approve", "deployment_runs"),
    _w("yoke deployment-runs get", "deployment_runs"),
    _w("yoke deployment-runs list", "deployment_runs"),
    _w("yoke deployment-runs update", "deployment_runs"),
    _w("yoke deployment-runs resolve-target-env", "deployment_runs"),
)


__all__ = ["WRAPPED_ROWS"]
