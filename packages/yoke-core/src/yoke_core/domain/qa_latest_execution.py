"""Select the latest QA execution, keeping browser reviews on their capture."""


def latest_execution_id_sql(requirement_id: str) -> str:
    """Newest run id; a detached agent verdict cannot replace a browser capture.

    Browser reviews resolve captures in place. Standalone agent verdict rows
    carry no execution identity and are not another execution of that case.
    Other methods, including requirements with only agent records, retain
    their ordinary newest-record ordering. Never filter by verdict: a newer
    pending or failed execution must replace an older passing one.
    """
    return (
        "SELECT latest.id FROM qa_runs latest "
        f"WHERE latest.qa_requirement_id = {requirement_id} "
        "AND (latest.performed_by <> 'agent' OR NOT EXISTS ("
        "SELECT 1 FROM qa_runs capture "
        f"WHERE capture.qa_requirement_id = {requirement_id} "
        "AND capture.performed_by = 'browser_substrate')) "
        "ORDER BY latest.id DESC LIMIT 1"
    )
