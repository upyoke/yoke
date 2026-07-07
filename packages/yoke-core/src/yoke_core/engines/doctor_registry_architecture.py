"""Architecture-fitness HC bundle for the Doctor registry.

Sibling registry slice carved out of :mod:`doctor_registry` so the
parent file stays under the 350-line authored-file limit, following the
same pattern as :mod:`doctor_registry_coordination` and
:mod:`doctor_registry_harness`. Owns the architecture-fitness health
checks (path-based, item-based, doc-drift, writer-authority, and
source/dependency boundary checks).

Public surface:

* :data:`ARCHITECTURE_HEALTH_CHECKS` — ordered list spliced into the
  parent registry's ``HEALTH_CHECKS``.
"""

from __future__ import annotations

from typing import List

from yoke_core.engines.doctor_hc_architecture import (
    hc_architecture_cross_cutting_entrypoint,
    hc_architecture_forbidden_edge,
    hc_architecture_unclassified_path,
)
from yoke_core.engines.doctor_hc_architecture_doc import (
    hc_architecture_model_doc_drift,
)
from yoke_core.engines.doctor_hc_architecture_items import (
    hc_architecture_impact_declaration,
    hc_architecture_scan_error,
)
from yoke_core.engines.doctor_hc_installer_live_tui_import_boundary import (
    HC_DESC as INSTALLER_LIVE_TUI_IMPORT_BOUNDARY_DESC,
    hc_installer_live_tui_import_boundary,
)
from yoke_core.engines.doctor_hc_platform_namespace_boundary import (
    HC_DESC as PLATFORM_NAMESPACE_BOUNDARY_DESC,
    hc_platform_namespace_boundary,
)
from yoke_core.engines.doctor_hc_server_checkout_independence import (
    HC_DESC as SERVER_CHECKOUT_INDEPENDENCE_DESC,
    hc_server_checkout_independence,
)
from yoke_core.engines.doctor_hc_workspace_anchored_writer_authority import (
    HC_DESC as WORKSPACE_WRITER_AUTHORITY_DESC,
    hc_workspace_anchored_writer_authority,
)
from yoke_core.engines.doctor_registry_types import HealthCheck


ARCHITECTURE_HEALTH_CHECKS: List[HealthCheck] = [
    HealthCheck(
        "architecture-unclassified-path",
        "Observed path has no inherited architecture domain or layer",
        hc_architecture_unclassified_path,
    ),
    HealthCheck(
        "architecture-forbidden-edge",
        "Recorded dependency edge violates the architecture model",
        hc_architecture_forbidden_edge,
    ),
    HealthCheck(
        "architecture-cross-cutting-entrypoint",
        "Non-approved module imports a guarded cross-cutting symbol",
        hc_architecture_cross_cutting_entrypoint,
    ),
    HealthCheck(
        "architecture-impact-declaration",
        "Item architecture_impact value is invalid or unresolved",
        hc_architecture_impact_declaration,
    ),
    HealthCheck(
        "architecture-scan-error",
        "Stored dependency_edges value is invalid or scan failed",
        hc_architecture_scan_error,
    ),
    HealthCheck(
        "architecture-model-doc-drift",
        "AGENTS.md Architecture Model section drift from payload",
        hc_architecture_model_doc_drift,
    ),
    HealthCheck(
        "workspace-anchored-writer-authority",
        WORKSPACE_WRITER_AUTHORITY_DESC,
        hc_workspace_anchored_writer_authority,
    ),
    HealthCheck(
        "server-checkout-independence",
        SERVER_CHECKOUT_INDEPENDENCE_DESC,
        hc_server_checkout_independence,
    ),
    HealthCheck(
        "installer-live-tui-import-boundary",
        INSTALLER_LIVE_TUI_IMPORT_BOUNDARY_DESC,
        hc_installer_live_tui_import_boundary,
    ),
    HealthCheck(
        "platform-namespace-boundary",
        PLATFORM_NAMESPACE_BOUNDARY_DESC,
        hc_platform_namespace_boundary,
    ),
]


__all__ = ["ARCHITECTURE_HEALTH_CHECKS"]
