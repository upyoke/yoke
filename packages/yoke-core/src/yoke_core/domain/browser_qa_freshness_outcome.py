"""What a deployment freshness check concluded, and why.

The reason codes live beside the failure type because they are one
vocabulary: every refusal names exactly which question went unanswered.
"No deployment was recorded", "the record names no commit", "the commit
differs", and "the deployment could not be asked" are four different
problems with four different recoveries, and a check that collapses them
sends its reader after the wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass


#: No ``ephemeral_environments`` row exists for the branch at all.
DEPLOYMENT_RECORD_MISSING = "deployment_record_missing"
#: A row exists, but it records no deployed commit to compare against.
DEPLOYED_SHA_UNKNOWN = "deployed_sha_unknown"
#: A deployed commit genuinely differs from the expected one.
SHA_MISMATCH = "sha_mismatch"
#: The configured identity endpoint could not be reached or refused to answer.
IDENTITY_PROOF_UNAVAILABLE = "identity_proof_unavailable"
#: The identity endpoint answered with something that is not a commit SHA.
IDENTITY_PROOF_MALFORMED = "identity_proof_malformed"
#: Freshness was established by asking one deployment, and the run was
#: then pointed at a different one. Evidence collected there would carry a
#: freshness claim nothing proved about it.
EXECUTION_TARGET_UNAUTHORIZED = "execution_target_unauthorized"
#: The project's identity configuration could not be read — denied,
#: unavailable, or malformed. Distinct from configuring none, because a
#: project that could not be asked never declined anything.
IDENTITY_CONFIG_UNREADABLE = "identity_config_unreadable"


@dataclass(frozen=True)
class FreshnessFailure:
    """Why a deployment freshness check refused, in both registers.

    ``reason`` is the stable code recorded on the run and read by tooling;
    ``message`` is the human sentence naming the branch, the commits, and
    what to do next. They are one object so a caller cannot record a reason
    that disagrees with the message it printed.
    """

    reason: str
    message: str


__all__ = [
    "DEPLOYED_SHA_UNKNOWN",
    "EXECUTION_TARGET_UNAUTHORIZED",
    "IDENTITY_CONFIG_UNREADABLE",
    "DEPLOYMENT_RECORD_MISSING",
    "IDENTITY_PROOF_MALFORMED",
    "IDENTITY_PROOF_UNAVAILABLE",
    "SHA_MISMATCH",
    "FreshnessFailure",
]
