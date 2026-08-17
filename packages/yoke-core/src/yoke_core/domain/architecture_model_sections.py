"""Validators for the optional architecture-model payload sections.

Sibling of :mod:`yoke_core.domain.architecture_model`, which owns the
required sections (layers, domains, cross-cutting entrypoints) and
composes these optional-section validators so the parent stays under
the authored-file cap. Same contract: pure validation, raises
:class:`yoke_core.domain.project_structure.ValidationError`, no DB
access.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.path_context import ARCHITECTURE_EXEMPTION_FAMILIES
from yoke_core.domain.project_structure import ValidationError


PACKAGE_LAYOUTS = frozenset({"package_under_root", "package_is_root"})


def validate_exemptions(exemptions: Any) -> None:
    """Validate the optional ``exemptions`` pattern list."""
    if exemptions is None:
        return
    if not isinstance(exemptions, list):
        raise ValidationError(
            "Family 'architecture_model' 'exemptions' must be a list of "
            f"{{glob, family}} objects when present "
            f"(got {type(exemptions).__name__})."
        )
    for idx, entry in enumerate(exemptions):
        where = f"'exemptions'[{idx}]"
        if not isinstance(entry, dict):
            raise ValidationError(
                f"Family 'architecture_model' {where} must be a "
                f"{{glob, family}} object (got {type(entry).__name__})."
            )
        glob = entry.get("glob")
        if not isinstance(glob, str) or not glob.strip():
            raise ValidationError(
                f"Family 'architecture_model' {where}.glob must be a "
                f"non-empty string (got {type(glob).__name__})."
            )
        family = entry.get("family")
        if family not in ARCHITECTURE_EXEMPTION_FAMILIES:
            raise ValidationError(
                f"Family 'architecture_model' {where}.family must be one "
                f"of {sorted(ARCHITECTURE_EXEMPTION_FAMILIES)}."
            )


def validate_package_roots(package_roots: Any) -> None:
    """Validate the optional ``package_roots`` layout mapping."""
    if package_roots is None:
        return
    if not isinstance(package_roots, dict):
        raise ValidationError(
            "Family 'architecture_model' 'package_roots' must be an object "
            "mapping package names to [{root, layout}] lists when present "
            f"(got {type(package_roots).__name__})."
        )
    for package, entries in package_roots.items():
        if not isinstance(package, str) or not package.strip():
            raise ValidationError(
                "Family 'architecture_model' package_roots keys must be "
                "non-empty package-name strings."
            )
        if not isinstance(entries, list) or not entries:
            raise ValidationError(
                f"Family 'architecture_model' package_roots[{package!r}] "
                "must be a non-empty list of {root, layout} objects."
            )
        for e_idx, entry in enumerate(entries):
            where = f"package_roots[{package!r}][{e_idx}]"
            if not isinstance(entry, dict):
                raise ValidationError(
                    f"Family 'architecture_model' {where} must be a "
                    f"{{root, layout}} object (got {type(entry).__name__})."
                )
            root = entry.get("root")
            if not isinstance(root, str) or not root.strip():
                raise ValidationError(
                    f"Family 'architecture_model' {where}.root must be a "
                    f"non-empty string (got {type(root).__name__})."
                )
            layout = entry.get("layout")
            if layout not in PACKAGE_LAYOUTS:
                raise ValidationError(
                    f"Family 'architecture_model' {where}.layout must be "
                    f"one of {sorted(PACKAGE_LAYOUTS)}."
                )


def validate_decisions(decisions: Any) -> None:
    """Validate the optional ``decisions`` rationale list."""
    if decisions is None:
        return
    if not isinstance(decisions, list):
        raise ValidationError(
            "Family 'architecture_model' 'decisions' must be a list of "
            f"{{id, rationale}} objects when present "
            f"(got {type(decisions).__name__})."
        )
    for idx, decision in enumerate(decisions):
        where = f"'decisions'[{idx}]"
        if not isinstance(decision, dict):
            raise ValidationError(
                f"Family 'architecture_model' {where} must be a "
                f"{{id, rationale}} object (got {type(decision).__name__})."
            )
        for field in ("id", "rationale"):
            value = decision.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(
                    f"Family 'architecture_model' {where}.{field} must be "
                    f"a non-empty string (got {type(value).__name__})."
                )


__all__ = [
    "PACKAGE_LAYOUTS",
    "validate_decisions",
    "validate_exemptions",
    "validate_package_roots",
]
