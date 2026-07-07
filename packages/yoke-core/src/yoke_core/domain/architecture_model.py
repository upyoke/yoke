"""Architecture model payload validator and derived-edge projector.

The ``architecture_model`` Project Structure family stores the project's
architecture-fitness map: domains, layers, allowed/forbidden edges per
layer, and the cross-cutting entrypoint registry.

Source-of-truth payload shape:

* ``domains`` - list of ``{"id": str, "path_roots": [glob, ...]}``.
* ``layers`` - list of ``{"id": str, "may_depend_on": [layer, ...],
  "forbidden_edges": [layer, ...]}``.
* ``cross_cutting_entrypoints`` - dict mapping entrypoint name to
  ``{"approved_modules": [module, ...],
    "approved_module_prefixes": [module_prefix, ...] (optional),
    "guarded_imports": [module.symbol, ...] (optional)}``.

Derived views: callers that want flat ``allowed_edges`` /
``forbidden_edges`` tables read them via :func:`derive_edges`. The
payload only stores the per-layer source; readers project.

Validation is pure: the validator raises
:class:`yoke_core.domain.project_structure.ValidationError` on any
shape miss. No DB access.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Mapping, Tuple

from yoke_core.domain.project_structure import ValidationError


def validate_payload(payload: Mapping[str, Any]) -> None:
    """Validate the ``architecture_model`` singleton payload shape."""
    if not isinstance(payload, Mapping):
        raise ValidationError(
            f"Family 'architecture_model' payload must be a JSON object "
            f"(got {type(payload).__name__})."
        )

    _validate_domains(payload.get("domains"))
    layer_ids = _validate_layers(payload.get("layers"))
    _validate_layer_cross_refs(payload["layers"], layer_ids)
    _validate_cross_cutting_entrypoints(
        payload.get("cross_cutting_entrypoints")
    )


def _validate_domains(domains: Any) -> FrozenSet[str]:
    if not isinstance(domains, list) or not domains:
        raise ValidationError(
            "Family 'architecture_model' payload must contain a non-empty "
            "'domains' list."
        )
    seen: List[str] = []
    for idx, dom in enumerate(domains):
        if not isinstance(dom, dict):
            raise ValidationError(
                f"Family 'architecture_model' 'domains'[{idx}] must be a "
                f"JSON object (got {type(dom).__name__})."
            )
        dom_id = dom.get("id")
        if not isinstance(dom_id, str) or not dom_id:
            raise ValidationError(
                f"Family 'architecture_model' 'domains'[{idx}] must have "
                "a non-empty string 'id'."
            )
        if dom_id in seen:
            raise ValidationError(
                f"Family 'architecture_model' duplicate domain id "
                f"'{dom_id}' at 'domains'[{idx}]."
            )
        seen.append(dom_id)
        roots = dom.get("path_roots")
        if not isinstance(roots, list) or not roots:
            raise ValidationError(
                f"Family 'architecture_model' 'domains'[{idx}].path_roots "
                "must be a non-empty list of glob/path strings."
            )
        for r_idx, root in enumerate(roots):
            if not isinstance(root, str) or not root.strip():
                raise ValidationError(
                    f"Family 'architecture_model' "
                    f"'domains'[{idx}].path_roots[{r_idx}] must be a "
                    f"non-empty string (got {type(root).__name__})."
                )
    return frozenset(seen)


def _validate_layers(layers: Any) -> FrozenSet[str]:
    if not isinstance(layers, list) or not layers:
        raise ValidationError(
            "Family 'architecture_model' payload must contain a non-empty "
            "'layers' list."
        )
    seen: List[str] = []
    for idx, layer in enumerate(layers):
        if not isinstance(layer, dict):
            raise ValidationError(
                f"Family 'architecture_model' 'layers'[{idx}] must be a "
                f"JSON object (got {type(layer).__name__})."
            )
        lid = layer.get("id")
        if not isinstance(lid, str) or not lid:
            raise ValidationError(
                f"Family 'architecture_model' 'layers'[{idx}] must have a "
                "non-empty string 'id'."
            )
        if lid in seen:
            raise ValidationError(
                f"Family 'architecture_model' duplicate layer id "
                f"'{lid}' at 'layers'[{idx}]."
            )
        seen.append(lid)
        for edge_field in ("may_depend_on", "forbidden_edges"):
            edges = layer.get(edge_field)
            if not isinstance(edges, list):
                raise ValidationError(
                    f"Family 'architecture_model' "
                    f"'layers'[{idx}].{edge_field} must be a list "
                    f"(got {type(edges).__name__})."
                )
            for e_idx, edge in enumerate(edges):
                if not isinstance(edge, str) or not edge.strip():
                    raise ValidationError(
                        f"Family 'architecture_model' "
                        f"'layers'[{idx}].{edge_field}[{e_idx}] must be a "
                        f"non-empty string (got {type(edge).__name__})."
                    )
    return frozenset(seen)


def _validate_layer_cross_refs(
    layers: List[Dict[str, Any]], layer_ids: FrozenSet[str]
) -> None:
    for idx, layer in enumerate(layers):
        for edge_field in ("may_depend_on", "forbidden_edges"):
            for edge in layer[edge_field]:
                if edge not in layer_ids:
                    raise ValidationError(
                        f"Family 'architecture_model' "
                        f"'layers'[{idx}].{edge_field} references unknown "
                        f"layer '{edge}'; known layers: "
                        f"{sorted(layer_ids)}."
                    )


def _validate_cross_cutting_entrypoints(entrypoints: Any) -> None:
    if not isinstance(entrypoints, dict) or not entrypoints:
        raise ValidationError(
            "Family 'architecture_model' payload must contain a non-empty "
            "'cross_cutting_entrypoints' object."
        )
    for ep_name, ep_value in entrypoints.items():
        if not isinstance(ep_name, str) or not ep_name:
            raise ValidationError(
                "Family 'architecture_model' cross_cutting_entrypoints "
                "keys must be non-empty strings."
            )
        if not isinstance(ep_value, dict):
            raise ValidationError(
                f"Family 'architecture_model' cross_cutting_entrypoints"
                f"[{ep_name!r}] must be a JSON object "
                f"(got {type(ep_value).__name__})."
            )
        approved = ep_value.get("approved_modules")
        if not isinstance(approved, list) or not approved:
            raise ValidationError(
                f"Family 'architecture_model' cross_cutting_entrypoints"
                f"[{ep_name!r}] must contain a non-empty "
                "'approved_modules' list."
            )
        for a_idx, mod in enumerate(approved):
            if not isinstance(mod, str) or not mod.strip():
                raise ValidationError(
                    f"Family 'architecture_model' "
                    f"cross_cutting_entrypoints[{ep_name!r}]"
                    f".approved_modules[{a_idx}] must be a non-empty "
                    f"string (got {type(mod).__name__})."
                )
        prefixes = ep_value.get("approved_module_prefixes")
        if prefixes is not None:
            if not isinstance(prefixes, list):
                raise ValidationError(
                    f"Family 'architecture_model' cross_cutting_entrypoints"
                    f"[{ep_name!r}].approved_module_prefixes must be a list "
                    f"when present (got {type(prefixes).__name__})."
                )
            for p_idx, prefix in enumerate(prefixes):
                if not isinstance(prefix, str) or not prefix.strip():
                    raise ValidationError(
                        f"Family 'architecture_model' "
                        f"cross_cutting_entrypoints[{ep_name!r}]"
                        f".approved_module_prefixes[{p_idx}] must be a "
                        f"non-empty string (got {type(prefix).__name__})."
                    )
        guarded = ep_value.get("guarded_imports")
        if guarded is None:
            continue
        if not isinstance(guarded, list):
            raise ValidationError(
                f"Family 'architecture_model' cross_cutting_entrypoints"
                f"[{ep_name!r}].guarded_imports must be a list when "
                f"present (got {type(guarded).__name__})."
            )
        for g_idx, guarded_import in enumerate(guarded):
            if not isinstance(guarded_import, str):
                valid_guard = False
            else:
                guard = guarded_import.strip()
                mod, sep, name = guard.rpartition(".")
                valid_guard = bool(sep and mod and name)
            if not valid_guard:
                raise ValidationError(
                    f"Family 'architecture_model' "
                    f"cross_cutting_entrypoints[{ep_name!r}]"
                    f".guarded_imports[{g_idx}] must be a non-empty "
                    "module.symbol string."
                )


def derive_edges(
    payload: Mapping[str, Any],
) -> Tuple[FrozenSet[Tuple[str, str]], FrozenSet[Tuple[str, str]]]:
    """Project ``(allowed_edges, forbidden_edges)`` from the layer source.

    Each edge is a ``(from_layer, to_layer)`` tuple. Allowed edges come
    from per-layer ``may_depend_on``; forbidden edges from per-layer
    ``forbidden_edges``. Exhaustive over what the validator accepted.
    """
    allowed: List[Tuple[str, str]] = []
    forbidden: List[Tuple[str, str]] = []
    for layer in payload.get("layers", []):
        lid = layer["id"]
        for to in layer.get("may_depend_on", []):
            allowed.append((lid, to))
        for to in layer.get("forbidden_edges", []):
            forbidden.append((lid, to))
    return frozenset(allowed), frozenset(forbidden)


__all__ = [
    "derive_edges",
    "validate_payload",
]
