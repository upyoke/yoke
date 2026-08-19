import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  ownTextContent,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function successful(result) {
  return { status: 200, envelope: { success: true, result } };
}

test("Packs separates Installed and Available with row-owned previews", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/packs";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return successful({ name: "Example" });
      }
      if (request.function === "projects.list") {
        return successful({ rows: [
          { id: 7, slug: "demo", name: "Demo" },
          { id: 8, slug: "second", name: "Second" },
        ] });
      }
      if (request.function === "packs.list") {
        if (request.payload.project === "8") {
          return successful({
            project_id: 8,
            project_slug: "second",
            repository_report: null,
            packs: [{
              slug: "container-runtime",
              name: "Container runtime",
              description: "Runs a web application in local containers.",
              status: "installed",
              installed_version: "1.0.0",
              latest_version: "1.0.0",
              dependencies: [],
              documentation: "docs/packs/container-runtime/README.md",
              file_count: 4,
            }],
          });
        }
        assert.deepEqual(request.payload, { project: "7" });
        return successful({
          project_id: 7,
          project_slug: "demo",
          repository_report: {
            receipt_digest: "abc",
            pack_count: 1,
            reported_at: "2026-07-17T10:00:00Z",
            fresh: false,
          },
          packs: [
            {
              slug: "container-runtime",
              name: "Container runtime",
              description: "Runs a web application in local containers.",
              status: "available",
              installed_version: null,
              latest_version: "1.0.0",
              dependencies: [],
              documentation: "docs/packs/container-runtime/README.md",
              file_count: 4,
            },
            {
              slug: "production-deploy",
              name: "Production deploy",
              description: "Deploys a reviewed release and supports urgent hotfixes.",
              status: "stale",
              installed_version: "1.0.0",
              latest_version: "1.1.0",
              dependencies: ["container-runtime"],
              documentation: "docs/packs/production-deploy/README.md",
              file_count: 8,
            },
          ],
        });
      }
      if (request.function === "packs.bundle.get") {
        assert.deepEqual(request.payload, {
          project: "7", pack: "production-deploy",
        });
        return successful({
          bundle_schema: 1,
          project_id: 7,
          project_slug: "",
          pack: "production-deploy",
          name: "Production deploy",
          description: "Deploy and hotfix delivery",
          version: "1.1.0",
          latest_version: "1.1.0",
          dependencies: ["container-runtime"],
          render_values: {},
          files: [
            { path: ".github/workflows/demo-deploy.yml", mode: 420 },
            { path: "scripts/deploy", mode: 493 },
          ],
          content_digest: "digest",
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();
  const screenText = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.ok(screenText.includes(
    "demo: repository report 2026-07-17T10:00:00Z (stale)",
  ));
  assert.ok(screenText.includes("second: no repository receipt reported"));
  assert.ok(screenText.includes("Runs a web application in local containers."));
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "H2")
      .map(ownTextContent),
    ["Installed", "Available", "Pack contents and checkout handoff"],
  );
  assert.deepEqual(
    allNodes(root).filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    [
      "Pack", "Project", "Installed", "Latest", "State",
      "Update — preview first",
    ],
  );
  assert.deepEqual(
    byClass(root, "pill").map((node) => node.textContent),
    ["update available", "current"],
  );
  assert.deepEqual(
    byClass(root, "pack-available-title").map((node) => node.textContent),
    ["container-runtime"],
  );
  assert.deepEqual(
    byClass(root, "pack-preview-action").map((node) => node.textContent),
    ["Inspect update", "Inspect get"],
  );
  const preview = byClass(root, "panel")[2];
  assert.equal(preview.hidden, true);
  assert.equal(byClass(root, "scope-bar").length, 0);
  assert.deepEqual(
    requests.filter((request) => request.function === "packs.list"),
    [
      { function: "packs.list", payload: { project: "7" } },
      { function: "packs.list", payload: { project: "8" } },
    ],
  );

  byClass(root, "pack-preview-action")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.equal(preview.hidden, false);
  const previewText = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.ok(previewText.includes(".github/workflows/demo-deploy.yml"));
  assert.ok(previewText.includes("0644"));
  assert.ok(previewText.includes("0755"));
  assert.ok(!previewText.includes(" 420 "));
  assert.ok(!previewText.includes(" 493 "));
  assert.ok(previewText.includes(
    "yoke packs update production-deploy . --project demo",
  ));
  assert.ok(previewText.includes("add --apply only after reviewing that preview"));
  assert.equal(
    requests.filter((request) => request.function === "packs.bundle.get").length,
    1,
  );
  mounted.unmount();
});
