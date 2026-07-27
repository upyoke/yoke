import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const styleRoot =
  "../../packages/yoke-core/src/yoke_core/ui/static/";

function style(name) {
  return readFileSync(new URL(`${styleRoot}${name}`, import.meta.url), "utf8");
}

test("Items roster preserves the prototype table at narrow widths", () => {
  const css = style("item_roster.css");
  for (const contract of [
    ".item-roster-wrap table.item-roster",
    "min-width: 720px",
    "var(--yoke-surface)",
    "var(--yoke-ink)",
    "@media (max-width: 960px)",
    "grid-template-columns: 1fr",
  ]) {
    assert.ok(css.includes(contract), contract);
  }
});

test("New Item controls stay theme-safe and reflow on mobile", () => {
  const css = [
    style("item_foundations.css"),
    style("item_intake.css"),
  ].join("\n");
  for (const contract of [
    "background: var(--yoke-bg)",
    "color: var(--yoke-ink)",
    "background: var(--yoke-accent-weak)",
    "@media (max-width: 640px)",
    "flex-wrap: wrap",
    "width: 100%",
  ]) {
    assert.ok(css.includes(contract), contract);
  }
  assert.doesNotMatch(css, /background:\s*#(?:fff|ffffff)\b/i);
});

test("All item detail spines collapse through theme-backed surfaces", () => {
  const css = style("item_details.css");
  for (const contract of [
    ".item-detail-grid",
    ".issue-detail .item-detail-grid",
    "grid-template-columns: minmax(0, 0.445fr) minmax(0, 1fr)",
    "background: var(--yoke-bg)",
    "color: var(--yoke-ink-2)",
    "@media (max-width: 1080px)",
    "@media (max-width: 860px)",
    "grid-template-columns: 1fr",
  ]) {
    assert.ok(css.includes(contract), contract);
  }
  assert.doesNotMatch(css, /background:\s*#(?:fff|ffffff)\b/i);
});
