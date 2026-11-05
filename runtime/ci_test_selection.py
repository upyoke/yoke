"""Keep interpreter-independent repository checks on the newest CI leg."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from yoke_core.tools.ci_shards import DURATIONS_PATH

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
    splitter = config.pluginmanager.get_plugin("pytestsplitplugin")
    if (splitter is not None and getattr(config.option, "splits", None)
            and os.environ.get("YOKE_CI_PYTHON_SCOPE") in {
        "all", "interpreter"
    }):
        config.pluginmanager.unregister(splitter)
        config.pluginmanager.register(_FileSplitter(splitter), "ci_file_splitter")


@dataclass(frozen=True)
class _File:
    nodeid: str

    def __str__(self):
        return self.nodeid


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


def scheduling_units(items):
    """Map each file to its indivisible unit: itself, or the product wheel files."""
    units = {}
    for item in items:
        filename = item.nodeid.split("::", 1)[0]
        units.setdefault(filename, filename)
        if not PRODUCT_WHEEL_FIXTURES.isdisjoint(item.fixturenames):
            units[filename] = PRODUCT_WHEEL_UNIT
    return units


def file_group(items, durations, splits, group):
    """Reuse least-duration scheduling with indivisible file fixture groups."""
    from pytest_split.algorithms import LeastDurationAlgorithm

    units = scheduling_units(items)
    weights = {}
    for filename, weight in file_weights(items, durations).items():
        weights[units[filename]] = weights.get(units[filename], 0) + weight
    selected = LeastDurationAlgorithm()(
        splits, [_File(unit) for unit in weights], weights
    )[group - 1]
    chosen = {unit.nodeid for unit in selected.selected}
    names = {filename for filename, unit in units.items() if unit in chosen}
    return names, selected.duration


class _FileSplitter:
    def __init__(self, splitter):
        self.splitter = splitter

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        fingerprint = {
            "count": len(items),
            "ids_sha256": hashlib.sha256(
                "\n".join(sorted(item.nodeid for item in items)).encode()
            ).hexdigest(),
            "profile_sha256": hashlib.sha256(json.dumps(
                self.splitter.cached_durations, sort_keys=True
            ).encode()).hexdigest(),
        }
        if hasattr(config, "workeroutput"):
            config.workeroutput["ci_collection"] = fingerprint
        else:
            self.splitter.writer.line("CI collection: " + json.dumps(fingerprint))
        names, estimate = file_group(
            items, self.splitter.cached_durations,
            config.option.splits, config.option.group,
        )
        kept, deselected = [], []
        for item in items:
            (kept if item.nodeid.split("::", 1)[0] in names else deselected).append(item)
        weights = file_weights(kept, self.splitter.cached_durations)
        kept.sort(key=lambda item: (
            -weights[item.nodeid.split("::", 1)[0]], item.nodeid.split("::", 1)[0]
        ))
        items[:] = kept
        config.hook.pytest_deselected(items=deselected)
        self.splitter.writer.line(
            f"[pytest-split] File group {config.option.group}/{config.option.splits} "
            f"(estimated duration: {estimate:.2f}s)"
        )


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
    profile = Path(__file__).resolve().parents[1] / DURATIONS_PATH
    try:
        durations = json.loads(profile.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise pytest.UsageError(
            f"ci_duration_profile_unavailable: {profile}: {error}; restore the "
            "checkout's timing profile or download this run's shared profile"
        ) from error
    weights = file_weights(items, durations)
    items.sort(key=lambda item: (-weights[item.nodeid.split("::", 1)[0]],
                                 item.nodeid.split("::", 1)[0]))
    fingerprint = {"count": len(items), "ids_sha256": hashlib.sha256(
        "\n".join(sorted(item.nodeid for item in items)).encode()).hexdigest()}
    if hasattr(config, "workeroutput"):
        config.workeroutput["ci_collection"] = fingerprint



@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    """Retain each worker's collection facts in the controller log."""
    fingerprint = getattr(node, "workeroutput", {}).get("ci_collection")
    if fingerprint:
        reporter = node.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(f"CI collection {node.gateway.id}: " + json.dumps(fingerprint))
