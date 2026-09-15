"""The served-revision reader itself: transport behavior, not an injected stub.

Injecting a read proves the judgement but says nothing about the fetch that
produces it. These exercise the real reader — its redirect rule, its error
classification, and its URL construction — because that is where "the answer
came from the host we authorized" is actually enforced.
"""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request

from yoke_core.domain import served_revision_probe as probe


SHA = "a" * 40


class TestOriginJoin:
    """The probe addresses an origin, not a string the caller assembled."""

    def test_a_target_url_with_a_path_still_probes_the_origin(self) -> None:
        """Configured targets carry paths; concatenation would miss the endpoint."""
        assert (
            probe.join_origin_path(
                "https://preview.example.test/app/dashboard", "/candidate-revision"
            )
            == "https://preview.example.test/candidate-revision"
        )

    def test_query_and_fragment_are_discarded(self) -> None:
        assert (
            probe.join_origin_path(
                "https://preview.example.test/x?a=1#f", "/candidate-revision"
            )
            == "https://preview.example.test/candidate-revision"
        )

    def test_a_missing_leading_slash_still_joins_once(self) -> None:
        assert (
            probe.join_origin_path("https://preview.example.test/", "rev")
            == "https://preview.example.test/rev"
        )


class TestRealReaderTransport:
    """The reader's own behavior on redirects, TLS, and status codes."""

    def test_a_redirect_leaving_the_origin_is_refused(self) -> None:
        """Following it would let another host answer for this deployment."""
        handler = probe.OriginBoundRedirect("https://preview.example.test/rev")
        assert (
            handler.redirect_request(
                urllib.request.Request("https://preview.example.test/rev"),
                None,
                302,
                "Found",
                {},
                "https://attacker.example.test/rev",
            )
            is None
        )

    def test_a_redirect_to_a_lookalike_host_is_refused(self) -> None:
        """Host suffixes are not origins: only an exact match may answer."""
        handler = probe.OriginBoundRedirect("https://preview.example.test")
        assert (
            handler.redirect_request(
                urllib.request.Request("https://preview.example.test/rev"),
                None,
                302,
                "Found",
                {},
                "https://preview.example.test.attacker.test/rev",
            )
            is None
        )

    def test_a_redirect_downgrading_the_scheme_is_refused(self) -> None:
        """http://host is a different origin from https://host."""
        handler = probe.OriginBoundRedirect("https://preview.example.test")
        assert (
            handler.redirect_request(
                urllib.request.Request("https://preview.example.test/rev"),
                None,
                302,
                "Found",
                {},
                "http://preview.example.test/rev",
            )
            is None
        )

    def test_a_redirect_within_the_origin_is_followed(self) -> None:
        """Same-origin redirects are ordinary routing, not an escape."""
        handler = probe.OriginBoundRedirect("https://preview.example.test")
        redirected = handler.redirect_request(
            urllib.request.Request("https://preview.example.test/rev"),
            None,
            302,
            "Found",
            {},
            "https://preview.example.test/rev/",
        )
        assert redirected is not None

    def test_a_tls_failure_is_classified_not_raised(self, monkeypatch) -> None:
        """An invalid certificate is an unverified answer, not a crash."""

        class _Failing:
            def open(self, *_args, **_kwargs):
                raise ssl.SSLError("certificate verify failed")

        monkeypatch.setattr(urllib.request, "build_opener", lambda *_: _Failing())
        read = probe.fetch_served_revision("https://preview.example.test/rev")
        assert read.status == 0
        assert "TLS verification failed" in read.error

    def test_a_404_is_classified_with_its_status(self, monkeypatch) -> None:
        class _NotFound:
            def open(self, *_args, **_kwargs):
                raise urllib.error.HTTPError(
                    "https://preview.example.test/rev", 404, "Not Found", {}, None
                )

        monkeypatch.setattr(urllib.request, "build_opener", lambda *_: _NotFound())
        read = probe.fetch_served_revision("https://preview.example.test/rev")
        assert read.status == 404
        assert "HTTP 404" in read.error

    def test_a_connection_error_is_classified(self, monkeypatch) -> None:
        class _Refused:
            def open(self, *_args, **_kwargs):
                raise OSError("connection refused")

        monkeypatch.setattr(urllib.request, "build_opener", lambda *_: _Refused())
        read = probe.fetch_served_revision("https://preview.example.test/rev")
        assert read.error == "connection refused"

    def test_a_non_200_never_counts_as_a_proof(self, monkeypatch) -> None:
        """Status is judged even when a body comes back."""
        outcome = probe.probe_served_revision(
            "https://preview.example.test",
            "/rev",
            expected_sha=SHA,
            fetch=lambda url: probe.ServedRevisionRead(status=503, body=SHA),
        )
        assert outcome.kind == probe.UNREACHABLE
        assert not outcome.proved
