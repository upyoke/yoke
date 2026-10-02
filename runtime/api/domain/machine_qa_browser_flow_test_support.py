"""A project-owned browser approval declaration for host-control tests."""

EXAMPLE_ORIGIN = "https://app.example.test"
EXAMPLE_FLOW = {
    "origins": [EXAMPLE_ORIGIN],
    "paths": ["/connect", "/machine"],
    "url_label": "Open:",
    "code_label": "One-time code:",
    "code_pattern": "[A-Z0-9]{4}-[A-Z0-9]{4}",
    "query_parameter": "user_code",
    "approval_target": 'role=button[name="Approve device"]',
    "rejected_statuses": ["denied", "expired", "missing", "used"],
    "denial_text": ["authorization denied in the browser", "authorization expired"],
}
