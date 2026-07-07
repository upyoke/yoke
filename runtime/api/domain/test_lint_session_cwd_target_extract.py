"""Focused tests for ``lint_session_cwd_target_extract``.

The broader ``test_lint_session_cwd`` suite covers the deny / allow
verdict integration. This sibling module owns the pure-extractor unit
tests so the integration file stays under the repo's file-line cap.
"""

from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_command_targets,
)


def test_heredoc_body_does_not_leak_targets():
    """regression: a heredoc-write whose body contains absolute
    paths (and a bare ``/`` token from prose like ``<claim-id>`` /
    ``<paths>``) must not surface those body tokens as command targets.
    """
    cmd = (
        "cat > /tmp/yok-1701-review.md <<'EOF'\n"
        "- The composer falls back to `<claim-id>` / `<paths>` placeholders.\n"
        "- Free paths: /tmp, /var/folders/...\n"
        "- Worktree: /Users/dev/yoke/.worktrees/YOK-1701\n"
        "- /etc/passwd reference\n"
        "EOF"
    )
    assert extract_command_targets(cmd) == ["/tmp/yok-1701-review.md"]


def test_unquoted_heredoc_tag_is_also_stripped():
    cmd = (
        "cat > /tmp/notes.md <<EOF\n"
        "/opt/elsewhere should not surface as a target\n"
        "EOF"
    )
    assert extract_command_targets(cmd) == ["/tmp/notes.md"]


def test_dash_heredoc_tag_is_also_stripped():
    cmd = (
        "cat > /tmp/notes.md <<-EOF\n"
        "\t/opt/elsewhere should not surface as a target\n"
        "\tEOF"
    )
    assert extract_command_targets(cmd) == ["/tmp/notes.md"]


def test_double_quoted_heredoc_tag_is_also_stripped():
    cmd = (
        "cat > /tmp/notes.md <<\"EOF\"\n"
        "/opt/elsewhere should not surface as a target\n"
        "EOF"
    )
    assert extract_command_targets(cmd) == ["/tmp/notes.md"]


def test_redirect_after_opener_is_still_caught():
    """``cat <<EOF > /opt/elsewhere/out`` puts the redirect target on
    the same line as the heredoc opener; the opener line must survive
    body stripping so the validator still sees the redirect target.
    """
    cmd = (
        "cat <<EOF > /opt/elsewhere/out.txt\n"
        "- body line /bad/path\n"
        "EOF"
    )
    assert extract_command_targets(cmd) == ["/opt/elsewhere/out.txt"]


def test_dash_heredoc_with_redirect_after_opener():
    cmd = (
        "cat <<-EOF > /opt/elsewhere/out.txt\n"
        "\t/bad/path\n"
        "\tEOF"
    )
    assert extract_command_targets(cmd) == ["/opt/elsewhere/out.txt"]


def test_multiple_positional_targets_on_opener_line_preserved():
    """``tee /tmp/a.log /var/log/b.log <<'EOF'`` has two real positional
    targets on the opener line. Both must survive body stripping.
    """
    cmd = (
        "tee /tmp/a.log /var/log/b.log <<'EOF'\n"
        "- /etc/passwd\n"
        "EOF"
    )
    assert extract_command_targets(cmd) == ["/tmp/a.log", "/var/log/b.log"]


# ---------------------------------------------------------------------------
# Positional-argument extractor rejects non-path "absolute"
# tokens that previously produced false-positive denials.
# ---------------------------------------------------------------------------


def test_sed_regex_anchor_does_not_extract():
    """``sed -n '/^## Heading/p'`` previously surfaced ``/^## Heading/``
    as a target. The positional-arg tightening rejects sed regex anchors
    (``/^``) so the lint stops false-positive denying these calls.
    """
    cmd = "sed -n '/^## Heading/p' /tmp/some-file"
    assert extract_command_targets(cmd) == ["/tmp/some-file"]


def test_url_versioned_path_does_not_extract():
    """``curl -X POST /v1/items`` previously surfaced ``/v1/items`` as a
    target. Versioned URL paths (``/v\\d+/``) are not filesystem paths.
    """
    cmd = "curl -X POST /v1/items"
    assert extract_command_targets(cmd) == []


def test_glob_pattern_does_not_extract():
    """Tokens containing glob metacharacters (``?``, ``*``, ``{``) are
    not extracted as path targets.
    """
    cmd = "find /tmp/* -name '*.py'"
    assert extract_command_targets(cmd) == []


def test_yok_n_placeholder_does_not_extract():
    """When skill prose like ``YOK-N`` is interpolated into a command,
    a token that begins with ``/N`` previously surfaced as an absolute
    path. The tightening rejects tokens that fail real-path checks; ``/N``
    alone is a valid simple path so we lean on context — confirm the
    typical placeholder shape ``/N/foo`` does not break extraction (the
    real failure mode lives in the ``/path-with:colon`` rule below).
    """
    cmd = "echo YOK-N affects /tmp/real-target"
    assert extract_command_targets(cmd) == ["/tmp/real-target"]


def test_colon_in_path_does_not_extract():
    """``localhost:8000/path`` styled tokens were previously surfaced.
    The mid-string-colon filter rejects them.
    """
    cmd = "curl /something:8000/path"
    assert extract_command_targets(cmd) == []


def test_brace_expansion_token_does_not_extract():
    cmd = "ls /tmp/{a,b}/c"
    assert extract_command_targets(cmd) == []


def test_real_absolute_path_still_extracts():
    """Regression guard: ordinary absolute filesystem paths are still
    surfaced after the tightening.
    """
    cmd = "cat /Users/dev/yoke/.worktrees/YOK-1/source.py"
    assert extract_command_targets(cmd) == [
        "/Users/dev/yoke/.worktrees/YOK-1/source.py"
    ]
