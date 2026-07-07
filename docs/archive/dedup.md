# Dedup System

Yoke uses a three-layer deduplication architecture to prevent duplicate backlog items.

## Layer 1: Agent-Level Semantic Dedup (Prompt-Driven)

Three commands run dedup before creating backlog items:

| Command | When | Dedup Step |
|---|---|---|
| `/yoke idea` | Every new item | Step 3 |
| `/yoke curate` | Ouroboros ticket proposals | Step 3a |

All three use the same two-pass logic:

### Pass 1 — Title Scan (Fast)
Query all items from the DB (`id`, `title`, `status`). Compare the proposed title against all existing titles using semantic similarity (LLM judgment, not exact string match). Covers both active and done items.

### Pass 2 — Body Scan (Thorough)
For title near-misses from Pass 1 and items sharing keywords/file references with the proposed title, read the full body content (everything below the YAML frontmatter). Scan for:

- **Sub-item lists** — numbered or bulleted lists describing component work or gaps
- **Gap descriptions** — sections like `## Gaps`, `## Sub-items`, or inline gap references
- **File/function references** — paths like `scripts/foo.sh` or function names matching the proposed scope
- **Implementation notes** — scope descriptions that overlap with the proposed item

For large backlogs (>200 items), Pass 2 is limited to near-misses and keyword matches from Pass 1 to maintain acceptable performance.

### Match Categories

Each match is classified into one of three types:

| Category | Meaning | Example |
|---|---|---|
| **Title match** | Proposed title ≈ existing title | "Fix HC count" matches "HC count stale in doctor" |
| **Body match** | Proposed title ≈ sub-item or gap in existing body | "Fix HC count" matches gap #1 listed in YOK-129's body |
| **Scope overlap** | Both items target the same files/functions | Both mention `doctor.sh` and HC count logic |

### What It Catches
- Direct duplicates (same problem, different wording)
- Subset duplicates (proposed item is a sub-item already described in another ticket's body)
- File-level overlap (two tickets targeting the same code area)

### What It Misses
- Cross-repo duplicates (no cross-project awareness)
- Deeply nested sub-items (only scans first-level body content)
- Semantic overlap that requires deep domain knowledge

## Layer 2: GitHub-Level Prefix Dedup (Code-Enforced)

`sync-to-github.sh` and `backlog-registry.sh` query GitHub before creating issues (YOK-117). They search for `[YOK-N]` prefixes to prevent creating duplicate GitHub issues even if local state files are lost.

This layer is orthogonal to Layer 1 — it prevents duplicate GitHub issues, not duplicate backlog items.

### What It Catches
- Re-creation of a GitHub issue for an existing backlog item
- Duplicate epic task issues during re-sync

### What It Misses
- Semantic duplicates with different YOK-N IDs (that's Layer 1's job)

## Manual Dedup Check

To manually check for duplicates:

1. **Title search:** `python3 -m runtime.api.cli.db_router query "SELECT id, title FROM items WHERE title LIKE '%keyword%'"`
2. **Body search:** `python3 -m runtime.api.cli.db_router items get YOK-N body` (check individual items)
3. **Backlog list:** `python3 -m runtime.api.cli.db_router items list --status all` and scan visually

## History

- **YOK-69**: Original dedup implementation (title-only)
- **YOK-117**: GitHub-level `[YOK-N]` prefix dedup
- **YOK-145**: Extended agent-level dedup to scan body content (two-pass)
- **YOK-150**: Planned — SQL full-text search over titles and bodies (subsumes YOK-145)
