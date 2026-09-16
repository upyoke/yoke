import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  ownTextContent,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  relativeAge,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_time.js";

test("strategy cards carry the corpus facts from one read", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/strategy";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [{ id: 1, slug: "yoke", name: "Yoke", public_item_prefix: "YOK" }],
            },
          },
        };
      }
      if (request.function === "strategy.surface.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              docs: [
                {
                  slug: "MISSION", title: "Mission statement",
                  summary: "What this is for.",
                  updated_at: "2026-07-01", updated_by: "ben",
                  parent_slug: null, revisions: 4,
                  execution_state: "available", archived: false,
                },
                {
                  slug: "CURRENT-PLAN", title: "Current plan",
                  summary: "What is happening now.",
                  updated_at: "2026-06-30", updated_by: null,
                  execution_owner_kind: "session",
                  execution_state: "claimed", archived: false,
                },
                {
                  slug: "OLD-PLAN", title: "Old plan",
                  updated_at: "2026-06-01", archived: true,
                  execution_state: "reference",
                },
              ],
              writes: [],
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  // Standing direction, the plans under it, and the archive, each as cards
  // rather than table rows — the authored summary is the readable fact, and
  // a column of them is not readable at table width.
  const slugs = byClass(root, "strategy-doc-slug").map(ownTextContent);
  assert.deepEqual(slugs, ["MISSION", "CURRENT-PLAN", "OLD-PLAN"]);
  assert.deepEqual(
    byClass(root, "strategy-doc-summary").map(ownTextContent),
    ["What this is for.", "What is happening now.", "No ## Summary heading"],
  );
  assert.deepEqual(
    byClass(root, "strategy-doc-prefix").map(ownTextContent),
    ["YOK", "YOK", "YOK"],
  );
  // The age says when, without the word the dot beside it already implies,
  // and stays a `<time>` so the exact moment is one press away.
  const ages = byClass(root, "strategy-doc-age").map((node) => node.textContent);
  assert.ok(ages[0].includes(relativeAge("2026-07-01")));
  assert.ok(!ages[0].includes("updated"));
  assert.equal(byClass(root, "strategy-doc-age")[0].children.at(-1).tagName, "TIME");

  // A session hold is a steering seat, and says so once.
  const claims = byClass(root, "strategy-doc-claim");
  assert.equal(claims.length, 1);
  assert.ok(claims[0].classList.contains("is-steering"));
  assert.equal(
    byClass(root, "strategy-doc-claim-label")[0].textContent, "STEERED",
  );
  assert.equal(byClass(claims[0], "steering-symbol").length, 1);
  assert.equal(byClass(root, "strategy-doc-claim-holder").length, 0);

  // The archive is reachable, closed, and counted.
  const archived = byClass(root, "work-band-archived-docs")[0];
  assert.equal(archived.open, false);
  assert.equal(byClass(archived, "work-band-count")[0].textContent, "1");

  // One read serves documents, claims and write history together.
  assert.equal(
    requests.filter(
      (request) => request.function === "strategy.surface.list",
    ).length,
    1,
  );
  mounted.unmount();
});
