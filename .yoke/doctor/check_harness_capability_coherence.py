"""Doctor HC: harness wake capability has exactly one authority.

``HC-harness-capability-coherence`` bundles the two ways a capability claim
goes stale, so neither can sit unnoticed:

* **Block drift** — invokes
  :func:`yoke_core.tools.render_harness_capability_inline.render` in
  ``check=True`` mode. Every surface that shows the capability to a reader
  renders it from :mod:`yoke_contracts.harness_wake_capability`, so a
  contract change that has not been re-rendered FAILs here.
* **Uncited claims** — invokes
  :func:`~yoke_core.tools.render_harness_capability_inline.uncited_capability_claims`.
  A sentence asserting what a harness can or cannot do with a wake primitive,
  written outside a generated block without naming the owning manifest fact,
  is the exact shape that drifted into stating the opposite of the measured
  answer. It FAILs with the file, line, and the citation to add.
* **Continuation contract** — invokes
  :func:`~yoke_core.tools.harness_continuation_coherence.continuation_contract_contradictions`.
  Teaching that an explicit-continuation harness (Codex ``write_stdin``)
  streams long commands automatically contradicts the measured contract.

The HC self-skips cleanly when the renderer is missing, which is every
non-source install: a project repo carries no harness teaching surfaces to
render.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_applicability import (
    CheckApplicability,
    PROJECT_SCOPE_SELF,
)
from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


APPLICABILITY = CheckApplicability(
    project_scope=PROJECT_SCOPE_SELF, requires_source_checkout=True,
)

HC_NAME = "HC-harness-capability-coherence"
HC_DESC = (
    "Harness wake capability renders from one contract and every claim "
    "names it"
)


def hc_harness_capability_coherence(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    try:
        from yoke_core.tools import harness_continuation_coherence as hcc
        from yoke_core.tools import render_harness_capability_inline as rhc
    except ImportError as exc:
        rec.record(
            HC_NAME, HC_DESC, "SKIP",
            f"harness capability renderer unavailable ({exc}); "
            "no teaching surfaces to check",
        )
        return

    repo_root = find_repo_root(Path(__file__))
    if repo_root is None:
        rec.record(
            HC_NAME, HC_DESC, "SKIP",
            "no source checkout resolved; nothing to scan",
        )
        return

    failures: list[str] = []

    result = rhc.render(repo_root, check=True)
    if result.changed or not result.ok:
        failures.append(
            rhc.format_render_drift(result, check=True).rstrip("\n")
        )

    findings = rhc.uncited_capability_claims(repo_root)
    continuations = hcc.continuation_contract_contradictions(repo_root)
    if findings:
        failures.append(rhc.format_uncited_summary(findings).rstrip("\n"))
    if continuations:
        failures.append(hcc.format_continuation_summary(continuations).rstrip("\n"))

    if failures:
        rec.record(HC_NAME, HC_DESC, "FAIL", "\n".join(failures))
        return

    rec.record(
        HC_NAME, HC_DESC, "PASS",
        f"{len(rhc.INVENTORY)} rendered surface(s) match "
        f"{rhc.CANONICAL_MODULE}; no uncited wake claims in "
        f"{len(rhc.CITATION_SCAN_SURFACES)} scanned surface(s)",
    )
