"""Client-readable serving floors for function ids.

The engine registry is the write-time check: ``register()`` refuses an id
absent from the previous serving set that omits ``minimum_serving_version``.
This map is what an HTTPS client may read without importing the engine, so
a typed ``function_version_skew`` can name the floor. Keep it equal to the
floors on registered entries; the registry tests bind the two.
"""

from __future__ import annotations

#: function_id -> minimum serving version. Do not copy already-served ids here.
FUNCTION_MINIMUM_SERVING_VERSIONS: dict[str, str] = {
    "actors.roster": "next-release",
    "actors.state.set": "next-release",
    "decision_requests.get": "next-release",
    "deployment_runs.driver.for_capture": "next-release",
    "deployment_runs.execution.attach_driver": "next-release",
    "deployment_runs.execution.release_driver": "next-release",
    "deployment_runs.remove_item": "next-release",
    "item_landings.list": "next-release",
    "item_landings.record": "next-release",
    "items.progress_log.get": "next-release",
    "merge_receipt.commits.attest": "next-release",
    "models.diff.run": "next-release",
    "models.publish.run": "next-release",
    "models.restore.run": "next-release",
    "models.revisions.run": "next-release",
    "projects.environment.list": "next-release",
    "qa.artifact.get": "next-release",
    "qa.artifact.rehome": "next-release",
    "qa.item_plan.retract": "next-release",
    "qa.requirement.rebind_target": "next-release",
    "strategy.coordination.append": "next-release",
    "strategy.doc.create": "next-release",
    "strategy.doc.replace": "next-release",
    "strategy.doc.section_replace": "next-release",
    "strategy.ingest.run": "next-release",
    "strategy.revision.restore": "next-release",
    "strategy.seed_defaults.run": "next-release",
}


def declared_minimum_serving_version(function_id: str) -> str:
    """Return the client-readable floor for *function_id*, or empty."""
    return str(FUNCTION_MINIMUM_SERVING_VERSIONS.get(function_id) or "").strip()


__all__ = [
    "FUNCTION_MINIMUM_SERVING_VERSIONS",
    "declared_minimum_serving_version",
]
