// Style contracts a work-item card and its delivery box depend on.
//
// Both were regressions a mounted test could not see: a delivery box the
// same colour as the card it sits on reads as loose lines of copy, and an
// age pushed to the card's right edge reads as a column unrelated to the
// chip it qualifies. Neither is visible in a DOM assertion, so the rule
// itself is what this pins.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function css(name) {
  return readFileSync(new URL(
    `../../packages/yoke-core/src/yoke_core/ui/static/${name}`,
    import.meta.url,
  ), "utf8");
}

// The declarations of the first rule whose selector list starts with
// `selector` — a shared rule names several selectors before its brace.
function rule(source, selector) {
  const match = source.match(
    new RegExp(`\\.universe-app-root ${selector}[^{]*\\{([^}]*)\\}`),
  );
  assert.ok(match, `${selector} has no rule`);
  return match[1];
}

test("a card's age follows its chip inline and is never pushed right", () => {
  const age = rule(css("universe_work_cards.css"), "\\.work-item-card-when");
  // `margin-left: auto` was what sent it to the right edge; `float` and a
  // `space-between` head would do the same thing by another route.
  assert.ok(!/margin-left:\s*auto/.test(age), "the age must not claim spare width");
  assert.ok(!/float/.test(age), "the age must not float");
  const head = rule(css("universe_work_cards.css"), "\\.work-item-card-head");
  assert.ok(
    !/justify-content:\s*space-between/.test(head),
    "the head must not spread its children to the row's edges",
  );
  // The head wraps, which is what lets a narrow row drop the age to a second
  // line instead of truncating it or overflowing.
  assert.match(head, /flex-wrap: wrap;/);
});

test("the delivery box is a white container lifted off the card fill", () => {
  const signals = css("universe_item_signals.css");
  const box = rule(signals, "\\.item-delivery");
  // The card itself is --yoke-surface; a box painted the same colour is the
  // flat grey list this replaced.
  assert.match(box, /background: var\(--yoke-bg\);/);
  assert.match(box, /border: 1px solid var\(--yoke-border\);/);
  assert.ok(
    !/background: var\(--yoke-surface\)/.test(box),
    "the box must not be the same fill as the card it sits on",
  );
  // The per-run sub-card keeps its own boxed form inside it.
  const subCard = rule(signals, "\\.item-deployment");
  assert.match(subCard, /border: 1px solid var\(--yoke-border\);/);
  assert.match(subCard, /border-radius: 8px;/);
  assert.match(rule(signals, "\\.item-deployment-icon\\.is-muted"), /--yoke-muted/);
});

test("no stylesheet still carries the flat-line Release rendering", () => {
  for (const name of ["universe_item_signals.css", "universe_work_cards.css"]) {
    assert.ok(
      !/release-delivery/.test(css(name)),
      `${name} still styles the replaced Release-only box`,
    );
  }
});
