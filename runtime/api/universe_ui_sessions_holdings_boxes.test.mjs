import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

function item(target, title) {
  return {
    holding_kind: "work_claim",
    target_kind: "item",
    target,
    item_ref: target,
    item_project_id: 1,
    item_project_sequence: Number(target.split("-")[1]),
    item_title: title,
    item_status: "implementing",
    item_workflow_id: "dash",
  };
}

function card(documentNode, extras = {}) {
  const currentItem = Object.hasOwn(extras, "currentItem")
    ? extras.currentItem
    : "YOK-20";
  return sessionCard(
    documentNode,
    {
      session_id: "session-1",
      liveness: "active",
      mode: extras.mode || "dash",
      executor: "codex",
      current_item: currentItem,
      current_item_project_id: 1,
      current_item_project_sequence: 20,
      current_item_title: "Current title",
      current_item_status: "implementing",
      current_item_workflow_id: "dash",
      activity_at: "2026-08-28T12:00:00Z",
      primary_item_stages: extras.stages || [
        { name: "idea", state: "complete", failure: null },
        { name: "implementing", state: "active", failure: null },
        {
          name: "reviewing implementation", state: "pending", failure: null,
        },
        { name: "done", state: "pending", failure: null },
      ],
      claims: [],
      holdings: extras.holdings || {
        current: [item("YOK-20", "Current title")],
        previous: [item("YOK-19", "Previous title")],
        previous_remainder: 0,
      },
      messageability: { messageable: false },
    },
    () => {},
  );
}

test("Currently held boxes in green while Previously held stays grey", () => {
  const rendered = card(new FakeDocument());
  const previous = byClass(rendered, "session-holdings-previous")[0];
  const current = byClass(rendered, "session-holdings-current")[0];
  assert.equal(
    byClass(previous, "session-holdings-label")[0].textContent,
    "Previously held",
  );
  assert.equal(
    byClass(current, "session-holdings-label")[0].textContent,
    "Currently held",
  );
  assert.equal(byClass(previous, "session-lock").length, 1);
  assert.equal(byClass(previous, "session-item-link")[0].textContent, "YOK-19");
  assert.equal(byClass(previous, "session-item-title").length, 0);
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_holdings.css",
    import.meta.url,
  ), "utf8");
  const steering = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_steering.css",
    import.meta.url,
  ), "utf8");
  assert.match(steering, /border-left: 3px solid var\(--yoke-accent\)/);
  assert.match(
    css,
    /\.session-holdings-current \{\n  border-left: 3px solid var\(--yoke-good\)/,
  );
  assert.match(
    css,
    /\.session-holdings-idle \{\n  border-left: 3px solid var\(--yoke-idle\)/,
  );
  assert.match(css, /padding: 7px 9px/);
  assert.match(css, /border-radius: 4px/);
});

test("the stage strip starts at the box edge with session-scoped contrast", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions_holdings.css",
    import.meta.url,
  ), "utf8");
  const strip = css.slice(css.indexOf(".session-item-stage-progress {"));
  assert.ok(
    !/padding-left/.test(strip.slice(0, strip.indexOf("}"))),
    "the strip is flush with the rest of the box, not indented",
  );
  // Pending segments carry a fill and an outline of their own here: the
  // shared inventory rule is left alone so that view is not retuned blind.
  assert.match(
    css,
    /\.session-item-stage-progress \.delivery-run-stage \{[\s\S]*?box-shadow: inset/,
  );
  for (const state of ["complete", "active", "failed", "stopped"]) {
    assert.match(
      css,
      new RegExp(
        `\\.session-item-stage-progress \\.delivery-run-stage\\[data-state="${state}"\\]`,
      ),
      `${state} segments are scoped to the session card`,
    );
  }
});

test("primary held item shows its complete workflow stage strip", () => {
  const rendered = card(new FakeDocument(), {
    holdings: {
      current: [
        item("YOK-21", "Extra title"),
        item("YOK-20", "Current title"),
      ],
      previous: [item("YOK-19", "Previous title")],
      previous_remainder: 0,
    },
  });
  const current = byClass(rendered, "session-holdings-current")[0];
  assert.deepEqual(
    byClass(current, "delivery-run-stage").map(
      (node) => node.getAttribute("data-state"),
    ),
    ["complete", "active", "pending", "pending"],
  );
  assert.deepEqual(
    byClass(current, "delivery-run-stage").map(
      (node) => node.getAttribute("title"),
    ),
    [
      "idea · complete",
      "implementing · active",
      "reviewing implementation · pending",
      "done · pending",
    ],
  );
  assert.equal(byClass(current, "session-item-stage-progress").length, 1);
  assert.equal(byClass(current, "session-item-title").length, 1);
});

test("the failed segment carries its failure without a second red line", () => {
  const rendered = card(new FakeDocument(), {
    stages: [
      { name: "idea", state: "complete", failure: null },
      { name: "implementing", state: "failed", failure: "QA failed" },
      {
        name: "reviewing implementation",
        state: "pending",
        failure: null,
      },
      { name: "done", state: "pending", failure: null },
    ],
  });

  // The strip is the whole progress row: no second node repeating the
  // failure as text underneath it.
  const progress = byClass(rendered, "session-item-stage-progress")[0];
  assert.equal(progress.children.length, 1);
  assert.equal(progress.children[0].className, "delivery-run-stages");
  const segment = byClass(rendered, "delivery-run-stage")[1];
  assert.equal(segment.getAttribute("data-state"), "failed");
  assert.equal(segment.getAttribute("title"), "implementing · QA failed");
  assert.match(
    byClass(rendered, "delivery-run-stages")[0].getAttribute("aria-label"),
    /implementing failed QA failed/,
  );
});

test("holder pill and age remain while the lifecycle strip stays item-only", () => {
  const rendered = card(new FakeDocument(), {
    mode: "parked",
  });
  const badge = byClass(rendered, "session-parked-badge")[0];
  assert.ok(!badge.className.includes("session-parked-badge-empty"));
  assert.equal(badge.hidden, false);
  assert.equal(byClass(rendered, "session-age").length, 1);
  assert.equal(byClass(rendered, "delivery-run-stages").length, 1);
});

test("steering or no-item sessions do not render an item stage strip", () => {
  const rendered = card(new FakeDocument(), {
    mode: "steer",
    currentItem: null,
    holdings: { current: [], previous: [], previous_remainder: 0 },
  });

  assert.equal(byClass(rendered, "delivery-run-stages").length, 0);
});

test("Previously held does not nest a Steering box for a released seat", () => {
  const rendered = card(new FakeDocument(), {
    holdings: {
      current: [],
      previous: [
        {
          holding_kind: "work_claim",
          target_kind: "steering",
          project_id: 1,
          strategy_docs: ["CURRENT-PLAN"],
          released_at: "2026-08-26T12:00:00Z",
        },
        item("YOK-19", "Previous title"),
      ],
      previous_remainder: 0,
    },
  });
  const previous = byClass(rendered, "session-holdings-previous")[0];
  assert.equal(byClass(previous, "session-steering-lead").length, 0);
  assert.equal(byClass(rendered, "session-steering-lead").length, 0);
  assert.equal(
    byClass(previous, "session-lock").map((node) => node.textContent)
      .includes("🛞"),
    true,
  );
});


test("an idle session boxes its empty state without a label", () => {
  const rendered = card(new FakeDocument(), {
    currentItem: null,
    holdings: { current: [], previous: [], previous_remainder: 0 },
  });
  const idle = byClass(rendered, "session-holdings-idle")[0];
  assert.equal(
    byClass(idle, "session-unassigned")[0].textContent,
    "No active work claims",
  );
  // Boxed like the held groups, but the line inside is the whole message.
  assert.equal(byClass(idle, "session-holdings-label").length, 0);
  assert.equal(byClass(rendered, "session-holdings-current").length, 0);
});

test("a claimed Dash still at status idea paints idea done, not active", () => {
  // The roster derives the strip from the pinned workflow and the live
  // claim, so the card paints what it is handed: the Dash worker's item
  // status is still idea while implementing is the active segment.
  const rendered = card(new FakeDocument(), {
    current_item_status: "idea",
    stages: [
      { name: "idea", state: "complete", failure: null },
      { name: "implementing", state: "active", failure: null },
      { name: "reviewing implementation", state: "pending", failure: null },
      { name: "done", state: "pending", failure: null },
    ],
  });

  const titles = byClass(rendered, "delivery-run-stage").map(
    (node) => node.getAttribute("title"),
  );
  assert.equal(titles[0], "idea · complete");
  assert.equal(titles[1], "implementing · active");
  assert.ok(!titles.includes("idea · active"));
});
