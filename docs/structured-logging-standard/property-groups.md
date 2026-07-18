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
| `environment` | TEXT | Yes | `production`, `staging`, `development`, `test` |
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
| `session_id` | TEXT | Yes | Session identifier. For agents: Claude session ID or fallback `$(date +%s)-$$`. For frontend: client-generated UUID persisted in sessionStorage. For backend: request-scoped or extracted from auth token. |
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
| `item_id` | TEXT | No | Backlog item. E.g., `42`. |
| `task_num` | INTEGER | No | Epic task number. |
| `tool_name` | TEXT | No | Tool invoked: `Bash`, `Read`, `Write`, `Edit`, `Grep`, `Glob`, `Agent`. |
| `worktree_path` | TEXT | No | Worktree path for the current dispatch. |

### page_props

Frontend-specific fields for page/view events.

| Field | Type | Required | Description |
|---|---|---|---|
| `page_url` | TEXT | Yes (for page events) | Full URL including query string. |
| `page_path` | TEXT | Yes (for page events) | URL path without query string or domain. |
| `page_title` | TEXT | No | Document title. |
| `referrer` | TEXT | No | Full referrer URL (from `document.referrer`). |

### device_props

Frontend-specific fields for device/browser context.

| Field | Type | Required | Description |
|---|---|---|---|
| `user_agent` | TEXT | No | Raw User-Agent string. |
| `browser` | TEXT | No | Parsed browser name and version. E.g., `Chrome 120`. |
| `os` | TEXT | No | Parsed OS. E.g., `macOS 14.2`, `Windows 11`. |
| `device_type` | TEXT | No | `desktop`, `mobile`, `tablet`. |

### marketing_attribution_props

Included on acquisition events and optionally on all frontend events for attribution analysis.

| Field | Type | Required | Description |
|---|---|---|---|
| `utm_source` | TEXT | No | Campaign source. E.g., `google`, `newsletter`. |
| `utm_medium` | TEXT | No | Campaign medium. E.g., `cpc`, `email`, `organic`. |
| `utm_campaign` | TEXT | No | Campaign name. |
| `utm_term` | TEXT | No | Paid search term. |
| `utm_content` | TEXT | No | Ad variation identifier. |
| `referrer_domain` | TEXT | No | Extracted domain from referrer. E.g., `google.com`. |
| `acquisition_channel` | TEXT | No | Inferred channel: `direct`, `organic`, `referral`, `paid`, `email`, `social`. |

### Group Requirements Per Source Type

| Property Group | agent | backend | frontend | system |
|---|---|---|---|---|
| event_props | **Required** | **Required** | **Required** | **Required** |
| system_props | **Required** | **Required** | **Required** | **Required** |
| actor_props | -- | **Required** | Receiver-stamped | -- |
| org_props | -- | Conditional | Conditional | -- |
| session_props | **Required** | **Required** | **Required** | **Required** |
| request_props | **Required** | **Required** | Optional | Optional |
| error_props | On error | On error | On error | On error |
| agent_props | **Required** | -- | -- | -- |
| page_props | -- | -- | **Required** | -- |
| device_props | -- | -- | **Required** | -- |
| marketing_attribution_props | -- | -- | On acquisition | -- |
| context | Optional | Optional | Optional | Optional |

---
