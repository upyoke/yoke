# Property Group Definitions

Cross-link back from [structured-logging-standard.md](../structured-logging-standard.md) for the canonical envelope, source-type composition, implementation templates, and the taxonomy appendix.

Property groups are named, reusable sets of fields. Every implementation (shell, Python, JS/TS) MUST use these exact field names. Groups compose into source-type-specific envelopes — see [source-type-composition.md](source-type-composition.md).

### event_props (REQUIRED on every event)

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | TEXT (UUID v4) | Yes | Globally unique event identifier. Idempotency key for deduplication. |
| `event_name` | TEXT | Yes | PascalCase event name. Verb-first: `PageViewed`, `HarnessToolCallCompleted`, `OrderCreated`. |
| `event_kind` | TEXT (enum) | Yes | `analytics`, `system`, `audit`, `security`, `metric`, `lifecycle`, `workflow` |
| `event_type` | TEXT | Yes | Project-specific free string for sub-categorization. E.g., `page_view`, `tool_call`, `api_request`. |
| `event_time` | TEXT (ISO 8601 UTC) | Yes | When the event occurred. Always UTC with `Z` suffix. |
| `event_outcome` | TEXT (enum) | No | `completed`, `failed`, `skipped`, or null. Null for fire-and-forget events. |
| `severity` | TEXT (enum) | Yes | `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL`. Defaults to `INFO`. |
| `source_type` | TEXT (enum) | Yes | `agent`, `backend`, `frontend`, `system`, `script`, `hook`, `skill` |
| `duration_ms` | INTEGER | No | Event duration in milliseconds. Null if not a timed operation. |

### system_props

| Field | Type | Required | Description |
|---|---|---|---|
| `environment` | TEXT | Yes | `prod`, `stage`, `local` |
| `service` | TEXT | Yes | Service identifier. E.g., `cli`, `api`, `web`, `worker`. |
| `service_version` | TEXT | No | Semver or commit hash. |
| `project` | TEXT | Yes | Project slug. E.g., `yoke`, `external-webapp`. |

### actor_props

| Field | Type | Required | Description |
|---|---|---|---|
| `actor_id` | INTEGER | Conditional | Authenticated engine actor. Resolved by the trusted receiver, never claimed by a browser client. |
| `is_anonymous` | BOOLEAN | No | True when no actor is authenticated. |

### org_props

| Field | Type | Required | Description |
|---|---|---|---|
| `org_id` | TEXT (UUID) | Conditional | Organization identifier. Required when org context exists. |
| `org_name` | TEXT | No | Organization display name. |
| `org_plan` | TEXT | No | Subscription plan: `free`, `pro`, `enterprise`. |

### session_props

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | TEXT | Yes | Session identifier. For agents: registered harness session identity; never fabricate a shell fallback. For frontend: client-generated UUID held in memory for the page lifetime. For backend: request-scoped or extracted from auth token. |
| `session_start_time` | TEXT (ISO 8601 UTC) | No | When the session began. |

### request_props

| Field | Type | Required | Description |
|---|---|---|---|
| `request_id` | TEXT (UUID) | No | Unique ID for this request. Auto-generated per API request. |
| `trace_id` | TEXT (UUID) | No | Distributed trace ID spanning multiple services. Propagated via headers. |
| `parent_id` | TEXT (UUID) | No | ID of the parent event for causality chains (e.g., dispatch chain link). |

### error_props

Included when `event_outcome = "failed"` or when explicitly logging an error condition.

| Field | Type | Required | Description |
|---|---|---|---|
| `error_code` | TEXT | No | Machine-readable error code. E.g., `ECONNREFUSED`, `PGCONNECT_TIMEOUT`. |
| `error_category` | TEXT (enum) | Yes (on error) | `agent_failure`, `hook_failure`, `db`, `git`, `dispatch`, `validation`, `external`, `unknown` |
| `error_message` | TEXT | Yes (on error) | Human-readable error description. Max 2KB. |
| `is_retryable` | BOOLEAN | No | Whether the operation can be retried. |
| `exception_type` | TEXT | No | Language-specific exception class. E.g., `ValueError`, `TypeError`. |
| `stacktrace` | TEXT | No | Stack trace, truncated to 4KB from tail. |

### agent_props

Agent-specific fields for Yoke CLI agent events.

| Field | Type | Required | Description |
|---|---|---|---|
| `agent` | TEXT | Yes (for agents) | Agent name: `engineer`, `tester`, `architect`, `product-manager`, `product-designer`, `simulator` |
| `item_id` | numeric text | No | Bare `items.id` in core JSON; indexed storage is INTEGER. Resolve a public ref before emission. |
| `task_num` | INTEGER | No | Epic task number. |
| `tool_name` | TEXT | No | Tool invoked: `Bash`, `Read`, `Write`, `Edit`, `Grep`, `Glob`, `Agent`. |
| `worktree_path` | TEXT | No | Worktree path for the current dispatch. |

### page_props

Frontend-specific fields for page/view events.

| Field | Type | Required | Description |
|---|---|---|---|
| `page_url` | TEXT | Yes (for page events) | URL with sensitive query parameters (including `user_code`), userinfo and fragment stripped, and sensitive path segments masked. |
| `page_path` | TEXT | Yes (for page events) | URL path without query string or domain; `/machine-approval/<code>` is stored as `/machine-approval/redacted`. A new page view is emitted only when this path changes. |
| `page_title` | TEXT | No | Document title. |
| `referrer` | TEXT | No | Referrer URL (from `document.referrer`), sanitized like `page_url`. |

### device_props

Frontend fields for browser and device context. The browser sends only
`user_agent` and `is_bot`. The collector derives the rest from the request
headers and overwrites any emitter value: it parses User-Agent (ua-parser in
Python, Bowser in TypeScript) and applies the `Sec-CH-UA-Platform` and
`Sec-CH-UA-Mobile` Client Hints when sent. Viewport size never decides device type.

| Field | Type | Required | Description |
|---|---|---|---|
| `user_agent` | TEXT | No | Raw User-Agent string from the browser. |
| `is_bot` | BOOLEAN | No | Collector-computed from the request User-Agent. |
| `browser` | TEXT | No | Collector-parsed browser name, as the parser names it. E.g., `Chrome`, `Mobile Safari`, `Electron`. |
| `browser_version` | TEXT | No | Collector-parsed browser version. E.g., `141.0.0.0`. |
| `os` | TEXT | No | `Sec-CH-UA-Platform` when sent, else the parsed OS name. E.g., `macOS`, `Windows`, `Android`, `iOS`. |
| `device_type` | TEXT | No | `mobile` when `Sec-CH-UA-Mobile` is `?1`; otherwise the parser's `tablet` or `mobile` classification, else `desktop`. Null when the request has no User-Agent. |

### marketing_attribution_props

Included on every frontend event when server capture succeeds. Required signup facts belong to the account/actor owner.

| Field | Type | Required | Description |
|---|---|---|---|
| `visitor_id` | TEXT | Yes after capture | Persistent anonymous id from server-set cookie. |
| `first_touch` | OBJECT | Yes after capture | Immutable first acquisition touch. |
| `last_touch` | OBJECT | Yes after capture | Updated on external-referrer or campaign/click-id visits. |

Each touch contains the five classic UTMs, utm_id, utm_source_platform, gclid,
fbclid, msclkid, li_fat_id, referrer_domain, acquisition_channel and captured_at.
Values are nullable except channel and time. See [attribution](marketing-attribution.md)
for rules and server storage.

---
