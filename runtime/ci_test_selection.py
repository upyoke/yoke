"""Keep interpreter-independent repository checks on the newest CI leg."""

import hashlib
import json
import os

import pytest

#: Tests using the installed product environment. Their files share one
#: shard so the product install that ``product_venv`` builds runs once.
PRODUCT_WHEEL_FIXTURES = frozenset({"product_venv", "product_wheelhouse"})
PRODUCT_WHEEL_UNIT = "product wheel files"


def version_independent(node_id: str, fixtures=()) -> bool:
    path = node_id.split("::", 1)[0]
    name = path.rsplit("/", 1)[-1]
    return (
        not PRODUCT_WHEEL_FIXTURES.isdisjoint(fixtures)
        or path.startswith("tests/teaching_prototype/")
        or name.endswith("_docs.py")
        or "_teaching" in name
        or name.startswith(
            (
                "test_path_snapshot",
                "test_install_bundle",
                "test_doctor_hc_",
                "test_doc_",
                "test_docs_",
                "test_generated_",
            )
        )
        or name
        in {
            "test_doctor_project_check_execution.py",
            "test_generated_block_render.py",
            "test_atlas_render_docs.py",
            "test_disposable_generated_paths_policy.py",
        }
    )


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "ci_version_independent: repository and installed-wheel checks"
    )


def file_weights(items, durations):
    """Aggregate measured cases, estimating new cases from the known mean."""
    known = [durations[i.nodeid] for i in items if i.nodeid in durations]
    fallback = sum(known) / len(known) if known else 1.0
    weights = {}
    for item in items:
        filename = item.nodeid.split("::", 1)[0]
        weights[filename] = weights.get(filename, 0) + durations.get(
            item.nodeid, fallback
        )
    return weights


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    scope = os.environ.get("YOKE_CI_PYTHON_SCOPE")
    if scope not in {"all", "interpreter"}:
        return
    kept, deselected = [], []
    for item in items:
        independent = version_independent(
            item.nodeid, item.fixturenames
        ) or item.get_closest_marker("ci_version_independent")
        (deselected if scope == "interpreter" and independent else kept).append(item)
    items[:] = kept
    config.hook.pytest_deselected(items=deselected)
    durations = json.loads(open(".test_durations", encoding="utf-8").read())
    weights = file_weights(items, durations)
    items.sort(key=lambda item: (-weights[item.nodeid.split("::", 1)[0]],
                                 item.nodeid.split("::", 1)[0]))
    fingerprint = {"count": len(items), "ids_sha256": hashlib.sha256(
        "\n".join(sorted(item.nodeid for item in items)).encode()).hexdigest()}
    if hasattr(config, "workeroutput"):
        config.workeroutput["ci_collection"] = fingerprint



@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    """Retain each worker's assigned collection facts in the controller log."""
    fingerprint = getattr(node, "workeroutput", {}).get("ci_collection")
    if fingerprint:
        reporter = node.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(f"CI collection {node.gateway.id}: " + json.dumps(fingerprint))
