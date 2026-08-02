# Path claim ownership and provenance

Path claims have one authority model and one registration-provenance model.
`owner_kind` selects exactly one of `owner_item_id`, `owner_session_id`, or
`owner_work_claim_id`. `registered_by_actor_id` and
`registered_by_session_id` record who created the row without granting that
registration context ownership of the paths.

The authority columns are the only runtime read/write surface. Existing rows
are classified before the former identity columns are removed, and the
typed-owner health check remains responsible for detecting malformed rows.
