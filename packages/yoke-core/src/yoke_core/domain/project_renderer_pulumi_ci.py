"""GitHub Actions delivery inputs derived from renderer settings."""

from __future__ import annotations

from collections.abc import Mapping

from yoke_contracts.github_origin import DEFAULT_GITHUB_API_URL

from yoke_core.domain import json_helper
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
)


#: Environment-settings key holding one environment's opt-in delivery grant,
#: and the exact keys a grant may state. Unknown keys are refused rather than
#: ignored: a misspelled bound is a bound that silently does not apply.
DELIVERY_AUTHORITY_KEY = "delivery_authority"
DELIVERY_AUTHORITY_FIELDS = (
    "instance_tags",
    "documents",
    "artifact_buckets",
    "artifact_key_prefixes",
)


def _delivery_authority(settings: ProjectRendererSettings) -> dict[str, object]:
    """Merge every environment's stated delivery grant into one descriptor.

    One role serves every environment of a project, so the grant it carries is
    the union of what each environment stated — an environment that states
    nothing contributes nothing. Merging here rather than in the stack keeps
    the stack reading a single descriptor whatever the project's shape.

    The union is lossless, which is the whole point of merging rather than
    picking: environments naming different buckets contribute all of them, and
    environments naming the same tag key with different values yield one
    selector accepting any of those values. Assigning the later value over the
    earlier one would silently strip an environment's authority — a role that
    reaches production and no longer reaches stage, with nothing to show why.
    """
    tags: dict[str, set[str]] = {}
    documents: set[str] = set()
    buckets: set[str] = set()
    prefixes: set[str] = set()
    for environment in settings.environments:
        stated = environment.settings.get(DELIVERY_AUTHORITY_KEY)
        if stated is None:
            continue
        if not isinstance(stated, Mapping):
            raise ValueError(f"{DELIVERY_AUTHORITY_KEY} must be a mapping")
        unknown = set(stated) - set(DELIVERY_AUTHORITY_FIELDS)
        if unknown:
            raise ValueError(
                f"unknown {DELIVERY_AUTHORITY_KEY} keys: " + ", ".join(sorted(unknown))
            )
        stated_tags = stated.get("instance_tags") or {}
        if not isinstance(stated_tags, Mapping):
            raise ValueError("instance_tags must be a mapping")
        for key, value in stated_tags.items():
            tags.setdefault(str(key), set()).update(
                _stated_tag_values(value, f"instance_tags[{key}]")
            )
        documents.update(_stated_strings(stated.get("documents"), "documents"))
        buckets.update(
            _stated_strings(stated.get("artifact_buckets"), "artifact_buckets")
        )
        prefixes.update(
            _stated_strings(
                stated.get("artifact_key_prefixes"), "artifact_key_prefixes"
            )
        )
    if not (tags or documents or buckets or prefixes):
        return {}
    return {
        "instance_tags": {key: sorted(values) for key, values in sorted(tags.items())},
        "documents": sorted(documents),
        "artifact_buckets": sorted(buckets),
        "artifact_key_prefixes": sorted(prefixes),
    }


def _stated_tag_values(value: object, label: str) -> set[str]:
    """Return one tag key's accepted values, stated singly or as a list."""
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    return _stated_strings(value, label)


def _stated_strings(values: object, label: str) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ValueError(f"{label} must be a list of strings")
    return {str(value).strip() for value in values if str(value).strip()}


def delivery_ci_values(settings: ProjectRendererSettings) -> dict[str, str]:
    """Return exact distribution resources and App-key deny resources."""
    distribution_buckets: set[str] = set()
    cloudfront_distribution_ids: set[str] = set()
    app_key_secret_arns: set[str] = set()
    for environment in settings.environments:
        distribution = environment.settings.get("distribution")
        if isinstance(distribution, dict):
            bucket = str(distribution.get("bucket_name") or "").strip()
            if bucket:
                distribution_buckets.add(bucket)
        github_app = environment.settings.get("github_app")
        if isinstance(github_app, dict):
            secret_arn = str(github_app.get("private_key_secret_arn") or "").strip()
            if secret_arn:
                app_key_secret_arns.add(secret_arn)
    site_cdn = settings.site_settings.get("cdn")
    cdn_sources = (
        [site_cdn]
        if isinstance(site_cdn, Mapping)
        else [entry for entry in site_cdn if isinstance(entry, Mapping)]
        if isinstance(site_cdn, list)
        else []
    )
    domain_capability = settings.capabilities.get("domain")
    if isinstance(domain_capability, Mapping):
        cdn_sources.append(domain_capability)
    for source in cdn_sources:
        distribution_id = str(source.get("distribution_id") or "").strip()
        if distribution_id:
            cloudfront_distribution_ids.add(distribution_id)
        distribution_ids = source.get("distribution_ids")
        if isinstance(distribution_ids, list):
            cloudfront_distribution_ids.update(
                str(value).strip() for value in distribution_ids if str(value).strip()
            )
    github = settings.capabilities.get("github", {})
    return {
        "github_api_url": str(github.get("api_url") or DEFAULT_GITHUB_API_URL).strip(),
        "delivery_distribution_bucket_names_json": (
            json_helper.dumps_compact(sorted(distribution_buckets))
        ),
        "delivery_cloudfront_distribution_ids_json": (
            json_helper.dumps_compact(sorted(cloudfront_distribution_ids))
        ),
        "github_app_private_key_secret_arns_json": (
            json_helper.dumps_compact(sorted(app_key_secret_arns))
        ),
        "delivery_authority_json": (
            json_helper.dumps_compact(_delivery_authority(settings))
        ),
    }


__all__ = [
    "DELIVERY_AUTHORITY_FIELDS",
    "DELIVERY_AUTHORITY_KEY",
    "delivery_ci_values",
]
