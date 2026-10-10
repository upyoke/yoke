"""Refuse an unacknowledged field-targeted section write on older servers."""

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.function_serving_floors import (
    FUNCTION_ARGUMENT_MINIMUM_SERVING_VERSIONS,
)


def verify_field_receipt(
    response: FunctionCallResponse, field: str
) -> FunctionCallResponse:
    if not response.success or (response.result or {}).get("field") == field:
        return response
    floor = FUNCTION_ARGUMENT_MINIMUM_SERVING_VERSIONS[
        "items.structured_field.section_upsert"
    ]["field"].minimum_serving_version
    return response.model_copy(
        update={
            "success": False,
            "error": FunctionError(
                code="section_upsert_field_unsupported",
                message=(
                    f"Field-targeted section upsert requires serving floor {floor}; "
                    "the success receipt did not echo the requested field. "
                    "The write may have landed as a top-level item section. "
                    "Inspect the item's field and sections before any new write; "
                    "ask the control-plane operator to provide a serving build at the floor."
                ),
            ),
        }
    )
