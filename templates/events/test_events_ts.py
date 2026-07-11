"""Structural tests for the reference ``events.ts`` template.

Companion file ``test_events_ts_api.py`` covers the ``api-route.ts``
sibling. Both files are grep-style validation of the canonical shapes
guaranteed by the TypeScript reference implementation under
``templates/events/`` — neither compiles the TypeScript.

Run::

    python3 -m pytest templates/events/test_events_ts.py templates/events/test_events_ts_api.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_EVENTS_TS = _HERE / "events.ts"
# The TS reference is split across four sibling files. Tests that scan for
# content patterns (types, prop builders, attribution helpers, builder shape,
# size limits, batching, graceful degradation, the page-viewed example) read
# the dependency-ordered concatenation via the ``events_ts_concat`` fixture so
# any cross-file token sequence (e.g. ``type EventOutcome`` declared in
# ``events_types.ts`` and used in ``events.ts``) remains greppable. Only
# ``TestEventsTsExports`` reads ``events_ts`` alone -- its substring
# assertions like ``"emitEvent,"`` exist specifically to verify the trailing
# ``export { ... };`` block in ``events.ts`` re-exports every public symbol;
# repointing it at the concatenation would let it pass even if that block
# were lost.
_EVENTS_TS_SPLIT = (
    _HERE / "events_types.ts",
    _HERE / "events_props.ts",
    _HERE / "events_attribution.ts",
    _HERE / "events.ts",
)


@pytest.fixture(scope="module")
def events_ts() -> str:
    assert _EVENTS_TS.is_file(), f"reference template missing: {_EVENTS_TS}"
    return _EVENTS_TS.read_text()


@pytest.fixture(scope="module")
def events_ts_concat() -> str:
    parts = []
    for path in _EVENTS_TS_SPLIT:
        assert path.is_file(), f"reference template missing: {path}"
        parts.append(path.read_text())
    return "\n".join(parts)


def _must_contain(blob: str, needle: str, label: str) -> None:
    assert needle in blob, f"{label}: pattern not found ({needle!r})"


# ---------------------------------------------------------------------------
# events.ts — type definitions
# ---------------------------------------------------------------------------

class TestEventsTsTypeDefinitions:
    def test_event_kind_type_defined(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "type EventKind", "EventKind")

    def test_source_type_defined(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "type SourceType", "SourceType")

    def test_severity_type_defined(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "type Severity", "Severity")

    def test_event_outcome_type_defined(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "type EventOutcome", "EventOutcome")

    def test_event_envelope_interface(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "interface EventEnvelope", "EventEnvelope")

    def test_emit_options_interface(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "interface EmitOptions", "EmitOptions")

    def test_attribution_data_interface(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "interface AttributionData", "AttributionData")


# ---------------------------------------------------------------------------
# events.ts — property group builders
# ---------------------------------------------------------------------------

class TestEventsTsPropertyGroupBuilders:
    @pytest.mark.parametrize("fn_name", [
        "getSystemProps",
        "getSessionProps",
        "getOrgProps",
        "getPageProps",
        "getDeviceProps",
        "getAttributionProps",
    ])
    def test_builder_defined(self, events_ts_concat: str, fn_name: str) -> None:
        _must_contain(events_ts_concat, f"function {fn_name}", fn_name)


# ---------------------------------------------------------------------------
# events.ts — system / session / user / page / device props
# ---------------------------------------------------------------------------

class TestEventsTsSystemProps:
    @pytest.mark.parametrize("needle,label", [
        ("NEXT_PUBLIC_APP_ENV", "system props use NEXT_PUBLIC_APP_ENV"),
        ("NEXT_PUBLIC_APP_VERSION", "system props use NEXT_PUBLIC_APP_VERSION"),
        ("NEXT_PUBLIC_PROJECT", "system props use NEXT_PUBLIC_PROJECT"),
        ("service: 'web'", "system props service is web"),
    ])
    def test_system_props_env_wiring(self, events_ts_concat: str, needle: str, label: str) -> None:
        _must_contain(events_ts_concat, needle, label)


class TestEventsTsSessionProps:
    @pytest.mark.parametrize("needle,label", [
        ("sessionStorage", "session uses sessionStorage"),
        ("crypto.randomUUID", "session uses crypto.randomUUID"),
        ("event_session_id", "session stores event_session_id"),
    ])
    def test_session_props_storage(self, events_ts_concat: str, needle: str, label: str) -> None:
        _must_contain(events_ts_concat, needle, label)


class TestEventsTsOrgProps:
    def test_org_id_field(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "org_id:", "org_id field")

    def test_actor_identity_is_server_stamped(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "stamp actor_id", "server actor identity")

    def test_retired_user_id_is_absent(self, events_ts_concat: str) -> None:
        assert "user_id:" not in events_ts_concat


class TestEventsTsPageProps:
    @pytest.mark.parametrize("needle,label", [
        ("window.location.href", "page_url from location.href"),
        ("window.location.pathname", "page_path from location.pathname"),
        ("document.title", "page_title from document.title"),
        ("document.referrer", "referrer from document.referrer"),
    ])
    def test_page_props_fields(self, events_ts_concat: str, needle: str, label: str) -> None:
        _must_contain(events_ts_concat, needle, label)


class TestEventsTsDeviceProps:
    @pytest.mark.parametrize("needle,label", [
        ("navigator.userAgent", "user_agent from navigator.userAgent"),
        ("function parseBrowser", "parseBrowser defined"),
        ("function parseOS", "parseOS defined"),
        ("function detectDeviceType", "detectDeviceType defined"),
        ("768", "mobile breakpoint 768"),
        ("1024", "tablet breakpoint 1024"),
    ])
    def test_device_props_fields(self, events_ts_concat: str, needle: str, label: str) -> None:
        _must_contain(events_ts_concat, needle, label)


# ---------------------------------------------------------------------------
# events.ts — attribution lifecycle
# ---------------------------------------------------------------------------

class TestEventsTsAttribution:
    @pytest.mark.parametrize("fn_name", [
        "captureAttribution",
        "getStoredAttribution",
        "extractReferrerDomain",
        "inferChannel",
        "getUtmFromUrl",
        "setCookie",
        "getCookie",
    ])
    def test_helper_defined(self, events_ts_concat: str, fn_name: str) -> None:
        _must_contain(events_ts_concat, f"function {fn_name}", fn_name)

    @pytest.mark.parametrize("needle,label", [
        ("yoke_attribution", "cookie name yoke_attribution"),
        ("COOKIE_DAYS = 30", "30-day cookie expiry"),
        ("SameSite=Lax", "cookie SameSite Lax"),
        ("Secure", "cookie Secure flag"),
    ])
    def test_cookie_config(self, events_ts_concat: str, needle: str, label: str) -> None:
        _must_contain(events_ts_concat, needle, label)

    @pytest.mark.parametrize("needle,label", [
        ("cpc|ppc|paid|ad", "paid channel detection regex"),
        ("utmMedium === 'email'", "email channel from utm_medium"),
        ("utmSource === 'email'", "email channel from utm_source"),
        ("utmSource === 'newsletter'", "newsletter source"),
        ("return 'social'", "social channel return"),
        ("return 'organic'", "organic channel return"),
        ("return 'referral'", "referral channel return"),
        ("return 'direct'", "direct channel return"),
    ])
    def test_channel_inference(self, events_ts_concat: str, needle: str, label: str) -> None:
        _must_contain(events_ts_concat, needle, label)

    @pytest.mark.parametrize("domain", [
        "google.com", "bing.com", "yahoo.com", "duckduckgo.com",
    ])
    def test_search_engines(self, events_ts_concat: str, domain: str) -> None:
        _must_contain(events_ts_concat, domain, f"search engine {domain}")

    @pytest.mark.parametrize("domain", [
        "facebook.com", "twitter.com", "x.com",
        "linkedin.com", "reddit.com", "threads.net",
    ])
    def test_social_domains(self, events_ts_concat: str, domain: str) -> None:
        _must_contain(events_ts_concat, domain, f"social domain {domain}")

    def test_strips_www_prefix(self, events_ts_concat: str) -> None:
        # The original shell test escaped the dot; the behavior is the same
        # regardless of how the regex is literally spelled, so just assert the
        # ``www\.`` anchor is present.
        _must_contain(events_ts_concat, "www\\.", "strips www prefix")


# ---------------------------------------------------------------------------
# events.ts — event builder / size limits / batching
# ---------------------------------------------------------------------------

class TestEventsTsBuilder:
    @pytest.mark.parametrize("needle,label", [
        ("function buildEvent", "buildEvent defined"),
        ("source_type: 'frontend'", "source_type is frontend"),
        ("event_id: crypto.randomUUID()", "event_id generated"),
        ("event_time: new Date().toISOString()", "event_time generated"),
    ])
    def test_build_event_shape(self, events_ts_concat: str, needle: str, label: str) -> None:
        _must_contain(events_ts_concat, needle, label)


class TestEventsTsSizeLimits:
    @pytest.mark.parametrize("needle,label", [
        ("MAX_ENVELOPE_BYTES = 65536", "64KB envelope limit constant"),
        ("MAX_CONTEXT_FIELD_BYTES = 2048", "2KB context field limit constant"),
        ("function enforceContextLimits", "enforceContextLimits defined"),
        ("_truncated", "truncation marker on oversized envelope"),
    ])
    def test_size_limits(self, events_ts_concat: str, needle: str, label: str) -> None:
        _must_contain(events_ts_concat, needle, label)


class TestEventsTsBatching:
    @pytest.mark.parametrize("needle,label", [
        ("function emitEvent", "emitEvent defined"),
        ("function flushEvents", "flushEvents defined"),
        ("BATCH_SIZE = 10", "batch size constant"),
        ("FLUSH_INTERVAL_MS = 5000", "flush interval constant"),
        ("API_ENDPOINT = '/api/events'", "API endpoint"),
        ("splice(0, 50)", "max 50 per request"),
        ("keepalive: true", "keepalive for page navigation"),
        ("visibilitychange", "visibilitychange listener"),
    ])
    def test_batching(self, events_ts_concat: str, needle: str, label: str) -> None:
        _must_contain(events_ts_concat, needle, label)


class TestEventsTsGracefulDegradation:
    def test_graceful_degradation_comment(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "Graceful degradation", "graceful degradation comment")

    def test_console_warn_on_failure(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "console.warn", "console.warn on failure")


class TestEventsTsPageViewedExample:
    def test_example_function(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "emitPageViewedExample", "PageViewed example function")

    def test_example_event_type(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "eventType: 'page_view'", "example uses page_view type")

    def test_example_event_kind(self, events_ts_concat: str) -> None:
        _must_contain(events_ts_concat, "kind: 'analytics'", "example uses analytics kind")


# ---------------------------------------------------------------------------
# events.ts — exports
# ---------------------------------------------------------------------------

class TestEventsTsExports:
    @pytest.mark.parametrize("needle", [
        "emitEvent,",
        "buildEvent,",
        "flushEvents,",
        "getSystemProps,",
        "getSessionProps,",
        "getOrgProps,",
        "getPageProps,",
        "getDeviceProps,",
        "getAttributionProps,",
        "captureAttribution,",
        "getStoredAttribution,",
        "extractReferrerDomain,",
        "inferChannel,",
        "type EventEnvelope,",
        "type EmitOptions,",
        "type AttributionData,",
    ])
    def test_export(self, events_ts: str, needle: str) -> None:
        _must_contain(events_ts, needle, f"export {needle}")
