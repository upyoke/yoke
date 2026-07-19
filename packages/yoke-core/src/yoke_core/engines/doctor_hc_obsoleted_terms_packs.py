"""Retired whole-project artifact vocabulary guarded after the Pack cutover."""

_PROJECT_ARTIFACT_SYMBOL = r"\bproject_" + "artifact" + r"s?\b"
_PROJECT_ARTIFACT_FUNCTION = r"\bprojects\." + "artifacts" + r"\.render\b"
_PROJECT_ARTIFACT_RECEIPT = r"\.yoke/" + "artifact-manifest" + r"\.json\b"
_TEMPLATES_CLI = r"\byoke\s+" + "templates" + r"\b"
_TEMPLATE_DEVIATIONS = r"\b" + "template-deviations" + r"\.md\b"
_TEMPLATE_DRIFT_CHECK = r"\bHC-" + "template-project-drift" + r"\b"
_ARCHITECTURE_TEMPLATE_FAMILY = r"\barchitecture_" + "template_managed" + r"\b"

PACK_RETIREMENT_PATTERNS = (
    _PROJECT_ARTIFACT_SYMBOL,
    _PROJECT_ARTIFACT_FUNCTION,
    _PROJECT_ARTIFACT_RECEIPT,
    _TEMPLATES_CLI,
    _TEMPLATE_DEVIATIONS,
    _TEMPLATE_DRIFT_CHECK,
    _ARCHITECTURE_TEMPLATE_FAMILY,
)

PACK_RETIREMENT_LABELS = {
    _PROJECT_ARTIFACT_SYMBOL: "project_artifact(s) (retired whole-project artifact subsystem)",
    _PROJECT_ARTIFACT_FUNCTION: "projects.artifacts.render (retired whole-project renderer)",
    _PROJECT_ARTIFACT_RECEIPT: ".yoke/artifact-manifest.json (retired whole-project manifest)",
    _TEMPLATES_CLI: "yoke templates (retired CLI replaced by Packs)",
    _TEMPLATE_DEVIATIONS: "template-deviations.md (retired drift ledger)",
    _TEMPLATE_DRIFT_CHECK: "HC-template-project-drift (retired drift check)",
    _ARCHITECTURE_TEMPLATE_FAMILY: (
        "architecture_template_managed (retired path family replaced by "
        "architecture_pack_source)"
    ),
}

__all__ = ["PACK_RETIREMENT_LABELS", "PACK_RETIREMENT_PATTERNS"]
