import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("QA styles use theme tokens and collapse at the declared breakpoints", () => {
  const staticRoot = new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/",
    import.meta.url,
  );
  const qaEntry = readFileSync(new URL("qa.css", staticRoot), "utf8");
  const source = [
    "qa_catalog.css",
    "qa_details.css",
    "qa_results.css",
  ].map((name) => readFileSync(new URL(name, staticRoot), "utf8")).join("\n");

  assert.match(qaEntry, /qa_catalog\.css.*qa_details\.css.*qa_results\.css/s);
  for (const token of [
    "--yoke-bg",
    "--yoke-surface",
    "--yoke-border",
    "--yoke-ink",
    "--yoke-muted",
    "--yoke-accent",
  ]) {
    assert.match(source, new RegExp(`var\\(${token}\\)`));
  }
  assert.doesNotMatch(source, /#[0-9a-f]{3,8}\b/i);
  assert.match(source, /@media \(max-width: 860px\)/);
  assert.match(source, /@media \(max-width: 560px\)/);
  assert.match(
    source,
    /\.qa-detail-grid,\s*\.qa-plan-detail-grid\s*\{\s*grid-template-columns: 1fr/s,
  );
  assert.match(
    source,
    /\.qa-key-values\s*\{\s*grid-template-columns: 1fr/s,
  );
});

test("Activity stat strip keeps the shared prototype geometry", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/qa_results.css",
    import.meta.url,
  ), "utf8");

  assert.match(
    css,
    /\.qa-stats \{[^}]*gap: 12px;[^}]*margin-bottom: 22px;/,
  );
  assert.match(
    css,
    /\.qa-stat \{[^}]*padding: 13px 15px;/,
  );
  assert.match(
    css,
    /\.qa-stat strong \{[^}]*font-size: 23px;[^}]*font-weight: 640;[^}]*letter-spacing: -\.02em;[^}]*font-variant-numeric: tabular-nums;/,
  );
});
