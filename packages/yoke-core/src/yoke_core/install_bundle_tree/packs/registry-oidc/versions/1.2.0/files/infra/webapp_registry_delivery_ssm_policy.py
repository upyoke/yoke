"""Opt-in SSM Run Command and artifact-transfer authority for the delivery role.

A delivery role that can run commands on an instance can run *any* command the
instance's own role permits, so this grant is the widest thing the registry
stack can hand out. It is therefore off unless a project asks for it, and every
part of it is bounded by a descriptor the project stated: which instances (by
resource tag), which documents, which bucket, which key prefixes.

Fail-closed is the whole design. A descriptor that is present but malformed
raises rather than degrading into a broader grant — the failure mode worth
preventing is a typo silently widening a resource to ``*``. A descriptor that
is absent yields no statement at all, which is why a project that never opts in
sees its policy unchanged.

Nothing here names a project, environment, bucket, repository, or tenant. The
caller supplies the values; this module only decides the statement shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: Read-only companions to SendCommand. Without them a caller can start a
#: command but never learn what it did, which turns every delivery into a
#: blind fire-and-forget.
_INVOCATION_READ_ACTIONS = (
    "ssm:GetCommandInvocation",
    "ssm:ListCommandInvocations",
    "ssm:ListCommands",
)


class SsmDeliveryConfigError(ValueError):
    """A delivery descriptor is present but not usable as stated."""


def _clean_strings(values: Any, *, label: str) -> tuple[str, ...]:
    """Return non-empty stripped strings, refusing anything that is not a list."""
    if values is None:
        return ()
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise SsmDeliveryConfigError(f"{label} must be a list of strings")
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise SsmDeliveryConfigError(f"{label} entries must be strings")
        text = value.strip()
        if text:
            cleaned.append(text)
    return tuple(sorted(set(cleaned)))


def _clean_tags(tags: Any) -> tuple[tuple[str, str], ...]:
    """Return the instance selector as sorted key/value pairs.

    A tag selector is what bounds SendCommand to this project's instances, so
    an empty or non-mapping selector is refused rather than omitted: dropping
    the condition would leave the action scoped to every instance in the
    account.
    """
    if tags is None:
        return ()
    if not isinstance(tags, Mapping):
        raise SsmDeliveryConfigError("instance_tags must be a mapping")
    pairs: list[tuple[str, str]] = []
    for key, value in tags.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SsmDeliveryConfigError("instance_tags keys and values must be strings")
        name, text = key.strip(), value.strip()
        if not name or not text:
            raise SsmDeliveryConfigError("instance_tags entries must be non-empty")
        pairs.append((name, text))
    return tuple(sorted(pairs))


def ssm_delivery_statements(
    *,
    region: str,
    account_id: str,
    instance_tags: Any,
    documents: Any,
) -> list[dict[str, object]]:
    """Statements letting the role run named documents on tag-selected instances.

    Both halves are required together. Documents without a selector would run
    anywhere; a selector without documents would run anything. Either alone is
    a configuration error, not a narrower grant.
    """
    selector = _clean_tags(instance_tags)
    document_names = _clean_strings(documents, label="documents")
    if not selector and not document_names:
        return []
    if not selector:
        raise SsmDeliveryConfigError(
            "ssm documents are configured without instance_tags; a document "
            "with no instance selector would be runnable on every instance in "
            "the account"
        )
    if not document_names:
        raise SsmDeliveryConfigError(
            "ssm instance_tags are configured without documents; a selector "
            "with no named document would allow any document to be run"
        )
    document_arns = [
        f"arn:aws:ssm:{region}:{account_id}:document/{name}"
        for name in document_names
    ]
    return [
        {
            "Sid": "RunDeliveryDocumentsOnProjectInstances",
            "Effect": "Allow",
            "Action": "ssm:SendCommand",
            "Resource": f"arn:aws:ec2:{region}:{account_id}:instance/*",
            "Condition": {
                "StringEquals": {
                    f"aws:ResourceTag/{name}": value for name, value in selector
                },
            },
        },
        {
            "Sid": "RunDeliveryDocuments",
            "Effect": "Allow",
            "Action": "ssm:SendCommand",
            "Resource": document_arns,
        },
        {
            "Sid": "ReadDeliveryCommandResults",
            "Effect": "Allow",
            "Action": list(_INVOCATION_READ_ACTIONS),
            "Resource": "*",
        },
    ]


def artifact_transfer_statements(
    *,
    bucket: Any,
    key_prefixes: Any,
) -> list[dict[str, object]]:
    """Statements letting the role move delivery artifacts under named prefixes.

    The prefixes are the bound. Granting the bucket without them would let a
    delivery read or overwrite anything the bucket holds, so a bucket stated
    without prefixes is refused.
    """
    if bucket is None:
        name = ""
    elif not isinstance(bucket, str):
        raise SsmDeliveryConfigError("artifact_bucket must be a string")
    else:
        name = bucket.strip()
    prefixes = _clean_strings(key_prefixes, label="artifact_key_prefixes")
    if not name and not prefixes:
        return []
    if not name:
        raise SsmDeliveryConfigError(
            "artifact_key_prefixes are configured without an artifact_bucket"
        )
    if not prefixes:
        raise SsmDeliveryConfigError(
            "artifact_bucket is configured without artifact_key_prefixes; the "
            "whole bucket is never the intended scope"
        )
    return [
        {
            "Sid": "ListDeliveryArtifactPrefixes",
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": f"arn:aws:s3:::{name}",
            "Condition": {
                "StringLike": {
                    "s3:prefix": [f"{prefix}*" for prefix in prefixes],
                },
            },
        },
        {
            "Sid": "TransferDeliveryArtifacts",
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject"],
            "Resource": [f"arn:aws:s3:::{name}/{prefix}*" for prefix in prefixes],
        },
    ]


@dataclass(frozen=True)
class DeliveryAuthority:
    """One project's opt-in delivery grant, as stated in its configuration.

    Held together rather than passed as four parallel arguments because the
    four values are one decision: they are validated together, they are
    rendered together, and stating a subset of them is an error.
    """

    instance_tags: Mapping[str, str] = field(default_factory=dict)
    documents: Sequence[str] = field(default_factory=tuple)
    artifact_bucket: str = ""
    artifact_key_prefixes: Sequence[str] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        """Whether this states nothing, and so grants nothing."""
        return not (
            self.instance_tags
            or self.documents
            or self.artifact_bucket.strip()
            or self.artifact_key_prefixes
        )

    def statements(self, *, region: str, account_id: str) -> list[dict[str, object]]:
        """Every statement this grant contributes, in a stable order."""
        return [
            *ssm_delivery_statements(
                region=region,
                account_id=account_id,
                instance_tags=self.instance_tags,
                documents=self.documents,
            ),
            *artifact_transfer_statements(
                bucket=self.artifact_bucket,
                key_prefixes=self.artifact_key_prefixes,
            ),
        ]


def delivery_authority_from_config(values: Any) -> DeliveryAuthority:
    """Build a grant from a stated configuration mapping.

    An absent or empty mapping is the normal case and yields an empty grant.
    Anything else that is not a mapping is refused: a scalar where a
    descriptor belongs means the configuration was not written as intended,
    and guessing at it is how a resource ends up wider than stated.
    """
    if values is None:
        return DeliveryAuthority()
    if not isinstance(values, Mapping):
        raise SsmDeliveryConfigError("delivery authority configuration must be a mapping")
    unknown = set(values) - {
        "instance_tags",
        "documents",
        "artifact_bucket",
        "artifact_key_prefixes",
    }
    if unknown:
        raise SsmDeliveryConfigError(
            "unknown delivery authority keys: " + ", ".join(sorted(unknown))
        )
    bucket = values.get("artifact_bucket")
    if bucket is not None and not isinstance(bucket, str):
        raise SsmDeliveryConfigError("artifact_bucket must be a string")
    return DeliveryAuthority(
        instance_tags=dict(_clean_tags(values.get("instance_tags"))),
        documents=_clean_strings(values.get("documents"), label="documents"),
        artifact_bucket=(bucket or "").strip(),
        artifact_key_prefixes=_clean_strings(
            values.get("artifact_key_prefixes"), label="artifact_key_prefixes"
        ),
    )


__all__ = [
    "DeliveryAuthority",
    "SsmDeliveryConfigError",
    "artifact_transfer_statements",
    "delivery_authority_from_config",
    "ssm_delivery_statements",
]
