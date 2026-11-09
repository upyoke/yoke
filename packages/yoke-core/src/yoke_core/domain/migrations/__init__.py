"""Current control-plane baseline and future ordered migration entries.

The predecessor manifest is temporary rollout input for ledger collapse, not
active history. Only hosted Stage and Production tenants exist; their exact
predecessor content identities are verified before any membership is replaced.
After collapse, rollback below the release carrying this baseline is unsupported.
Future data transformations use numbered scripts after the baseline ordinal.
"""

HISTORY_BASELINE = {
    "name": "0106_baseline",
    "content_sha256": "e186ea2a939a1ae1451e96a69a25c9bfda163f0f92d0e28b48dc89913dea23dc",
    "minimum_serving_version": "next-release",
    "predecessor_manifest": "released_history_digests.json",
    "adoption_evidence_table": "migration_content_adoptions",
}
