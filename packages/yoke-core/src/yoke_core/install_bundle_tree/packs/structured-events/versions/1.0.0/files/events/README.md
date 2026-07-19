# Structured Events Pack Files

Reference implementations for backend Python, frontend TypeScript, and a
Next.js receiver. The Pack installs every file together; keep the relevant
language group and remove the others as normal project customization.

## Files

| File | Source Type | Language |
|------|------------|----------|
| `events.py` (+ `events_props.py` sibling) | backend | Python |
| `events.ts` (+ three `events_*.ts` siblings) | frontend | TypeScript |
| `api-route.ts` | frontend API | TypeScript |

### Backend Python files

The Python reference is split across two sibling files to keep each file under the 350-line ceiling. Copy **both** as a unit -- `events.py` imports from `events_props` (no package prefix), so the files must live next to each other on `sys.path`:

| File | Contents |
|------|----------|
| `events_props.py` | Property group builders -- `get_system_props`, `get_request_props`, `get_actor_props`, `get_org_props`, `get_session_props`, `get_error_props`. Resolves fields from explicit arguments with environment-variable fallbacks for system props. |
| `events.py` | Main module -- `build_event` (envelope assembly with size-limit enforcement), `emit_event` / `emit_event_obj` (build + emit), the `_emit` destination dispatcher (stdout / file / HTTP), the `UserLoggedIn` example, and a re-export block exposing every prop-builder name from `events_props.py` so consumers continue to write `from events import emit_event, get_system_props` without caring about the internal split. |

The two files import from each other via the bare module name `events_props` (e.g. `from events_props import get_system_props`), so they must be copied as a unit and placed in the same directory.

### Frontend TypeScript files

The TypeScript reference is split across four sibling files for readability and to keep each file under the 350-line ceiling. Copy **all four** as a unit -- the relative `import` statements between them assume they live next to each other:

| File | Contents |
|------|----------|
| `events_types.ts` | Shared type aliases (`EventKind`, `SourceType`, `Severity`, `EventOutcome`), the `EventEnvelope` and `EmitOptions` interfaces, the `AttributionData` type, and the size-limit constants (`MAX_ENVELOPE_BYTES`, `MAX_CONTEXT_FIELD_BYTES`). |
| `events_props.ts` | Property group builders -- `getSystemProps`, `getSessionProps`, `getOrgProps`, `getPageProps`, `getDeviceProps`, plus the `parseBrowser` / `parseOS` / `detectDeviceType` helpers. |
| `events_attribution.ts` | Marketing attribution lifecycle -- `captureAttribution`, `getStoredAttribution`, `extractReferrerDomain`, `inferChannel`, `getUtmFromUrl`, `setCookie`, `getCookie`, plus the search-engine and social-domain lookup tables. |
| `events.ts` | Main module -- `buildEvent`, `enforceContextLimits`, `emitEvent`, `flushEvents`, the visibilitychange flush hook, the `emitPageViewedExample` example, and a single trailing `export { ... };` block re-exporting every public symbol so consumers continue to write `import { emitEvent } from './events'` without caring about the internal split. |

The four files import from each other via relative paths (e.g. `import type { AttributionData } from './events_types';`), so they must be copied as a unit and placed in the same directory.

## Python Emitter (Backend)

### 1. Copy into your project

Copy both Python files into your project's `lib/` directory (they import from each other via the bare module name `events_props` and must live side-by-side on `sys.path`):

```bash
cp events.py events_props.py /path/to/your/project/lib/
```

After copying, `from events import emit_event` continues to work unchanged: the re-export block in `events.py` exposes every public symbol from `events_props.py`.

### 2. Configure environment variables (or pass explicitly)

The Python emitter resolves system props from environment variables with sensible defaults:

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_ENV` | `development` | Environment name |
| `SERVICE_NAME` | `api` | Service identifier |
| `SERVICE_VERSION` | `None` | Semantic version |
| `PROJECT` | `{{project_name}}` | Project identifier |

You can override any of these by passing explicit arguments to `get_system_props()`.

### 3. Emit events

**Quick style** -- build and emit in one call:

```python
from events import emit_event

emit_event(
    name="OrderCreated",
    kind="audit",
    event_type="order",
    outcome="completed",
    duration_ms=89,
    actor_id=17,
    context={"order_id": "ord_p6q7r8s9", "total_cents": 4999},
)
```

**Composable style** -- build property groups separately, then assemble:

```python
from events import (
    build_event, emit_event_obj,
    get_system_props, get_actor_props, get_org_props,
    get_session_props, get_request_props,
)

system = get_system_props(service="api", project="external-webapp")
actor = get_actor_props(actor_id=17)
org = get_org_props(org_id="org_x1y2z3", org_name="Acme Corp", org_plan="pro")
session = get_session_props(session_id="sess_abc123")
request = get_request_props(request_id="req_xyz789")

event = build_event(
    name="UserLoggedIn",
    kind="audit",
    event_type="auth",
    outcome="completed",
    context={"login_method": "oauth", "provider": "google"},
    **system, **actor, **org, **session, **request,
)
emit_event_obj(event)
```

### 4. Emission destinations

The `destination` parameter controls where events go:

| Value | Behavior |
|-------|----------|
| `"stdout"` (default) | Prints JSON to stdout |
| `"file:/path/to/log"` | Appends JSON line to file |
| `"http://endpoint"` | POSTs `{"events": [event]}` to URL |

All emission failures are silently swallowed (graceful degradation).

## TypeScript Emitter (Frontend)

### 1. Copy into your Next.js project

Copy all four `events_*.ts` files into your project's `lib/` directory (they import from each other via relative paths and must live side-by-side):

```bash
cp events.ts events_types.ts events_props.ts events_attribution.ts /path/to/your/project/lib/
cp api-route.ts /path/to/your/project/app/api/events/route.ts
```

After copying, `import { emitEvent } from '@/lib/events'` continues to work unchanged: the trailing re-export block in `events.ts` exposes every public symbol from the three sibling files.

### 2. Configure environment variables

The TS emitter uses `NEXT_PUBLIC_` prefixed env vars for client-side access:

| Variable | Default | Purpose |
|----------|---------|---------|
| `NEXT_PUBLIC_APP_ENV` | `development` | Environment name |
| `NEXT_PUBLIC_APP_VERSION` | `null` | Semantic version |
| `NEXT_PUBLIC_PROJECT` | `{{project_name}}` | Project identifier |

### 3. Initialize attribution capture

Call `captureAttribution()` once on app initialization to capture UTM parameters and referrer data:

```typescript
// In _app.tsx or layout.tsx
import { captureAttribution } from '@/lib/events';

// On mount
captureAttribution();
```

### 4. Emit events

```typescript
import { emitEvent } from '@/lib/events';

// Simple page view
emitEvent({
  name: 'PageViewed',
  kind: 'analytics',
  eventType: 'page_view',
  context: { tab: 'orders', items_visible: 25 },
  orgId: 'org_x1y2z3',
});

// Button click
emitEvent({
  name: 'ButtonClicked',
  kind: 'analytics',
  eventType: 'interaction',
  outcome: 'completed',
  context: { button_id: 'checkout', position: 'hero' },
});
```

Events are automatically batched (up to 10 events or every 5 seconds) and flushed to `/api/events`. The queue is also flushed when the page becomes hidden (tab switch, navigation) using `keepalive` to survive page transitions.

### 5. API route

The `api-route.ts` file is a Next.js App Router API route that receives batched events. By default it logs events to stdout as JSON lines. Replace the storage section with your actual backend (database insert, API proxy, or log file).

Validation enforced by the route:
- Request body must contain an `events` array (1..50 items)
- Each event must have `event_id`, `event_name`, `event_kind`, `event_type`, `event_time`
- `event_kind` must be a valid enum value
- Total request body must not exceed 512 KB

## Property Groups

### Python (Backend)

Each `get_*_props()` function returns a flat dict of fields for one property group defined in the standard. Groups are merged into the root envelope via `**kwargs` -- there is no nesting.

| Function | Standard Group | Required For |
|----------|---------------|-------------|
| `get_system_props()` | system_props | All source types |
| `get_actor_props()` | actor_props | backend after authentication |
| `get_org_props()` | org_props | Conditional (when org context exists) |
| `get_session_props()` | session_props | All source types |
| `get_request_props()` | request_props | backend |
| `get_error_props()` | error_props | Conditional (on failure) |

### TypeScript (Frontend)

All property groups are auto-resolved by `buildEvent()`. The caller only needs to provide event-specific options.

| Function | Standard Group | Behavior |
|----------|---------------|----------|
| `getSystemProps()` | system_props | Resolves from `NEXT_PUBLIC_*` env vars |
| `getSessionProps()` | session_props | Auto-generates session ID in sessionStorage |
| `getOrgProps()` | org_props | Emits org context; the receiver stamps authenticated `actor_id` |
| `getPageProps()` | page_props | Reads from `window.location` and `document` |
| `getDeviceProps()` | device_props | Parses user agent + viewport width |
| `getAttributionProps()` | marketing_attribution_props | Reads from cookie/sessionStorage |

## Marketing Attribution

The TypeScript emitter includes full marketing attribution tracking (Section E of the standard):

- **First-touch capture** on initial page load (UTM params + referrer)
- **Last-touch override** when new UTM params are present
- **30-day rolling cookie** (`yoke_attribution`) with SameSite=Lax
- **sessionStorage fallback** for current-session attribution
- **Channel inference** with 6 priority rules: paid > email > social > organic > referral > direct
- **Referrer domain extraction** with www. prefix stripping

## Size Limits

Enforced by both `build_event()` (Python) and `buildEvent()` (TypeScript):

- Total envelope: 64 KB
- Individual context string fields: 2 KB (truncated)
- Stacktrace (Python only): 4 KB (truncated from tail)
- Envelopes exceeding 64 KB have their context replaced with `{"_truncated": true}`

## Running Tests

```bash
# Python tests
python3 -m pytest test_events.py -v

# TypeScript structural tests
python3 -m pytest test_events_ts.py -v
```

## Running the Examples

```bash
# Python: UserLoggedIn audit event with all property groups
python events.py
```

The TypeScript example (`emitPageViewedExample`) requires a browser environment. It builds a complete PageViewed analytics event with all frontend property groups (system, session, user, page, device, attribution).
