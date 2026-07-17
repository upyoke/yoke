import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

// A served status payload in the engine's own shape. Every status word and
// reason below is a fixture string: anything the view shows beyond these
// would be hardcoded vocabulary — the assertion this fixture exists for.
function boundStatusFixture(overrides = {}) {
  return {
    project: "yoke",
    github_repo: "example-org/example-repo",
    default_branch: "main",
    github_sync_mode: "enabled",
    bound: true,
    binding: {
      project_id: 1,
      installation_id: "inst-31",
      repository_id: "repo-9",
      api_url: "https://api.github.com",
      github_repo: "example-org/example-repo",
      default_branch: "main",
      status: "active",
      permissions: { contents: "write" },
      last_verified_at: "2026-07-01T10:00:00Z",
      last_error: "",
      last_sync_at: "2026-07-02T08:30:00Z",
      last_sync_outcome: "success",
      last_sync_error: "",
    },
    installation: {
      installation_id: "inst-31",
      api_url: "https://api.github.com",
      account_id: "acct-4",
      account_login: "example-org",
      account_type: "Organization",
      repository_selection: "selected",
      permissions: { contents: "write" },
      status: "active",
      last_verified_at: "2026-07-01T10:00:00Z",
      last_error: "",
    },
    permission_status: { status: "satisfied", missing: [] },
    automation: { available: true, reason: "bound" },
    ...overrides,
  };
}

function githubClient(statusResult) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "projects.github_binding.status") {
        return okEnvelope(statusResult);
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountGithub(t, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/github?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { root, mounted };
}

function panelTitles(root) {
  return allNodes(root)
    .filter((node) => node.tagName === "H2")
    .map((node) => node.textContent);
}

function viewText(root) {
  const view = byClass(root, "view-host")[0];
  return allNodes(view).map((node) => node.textContent || "").join(" ");
}

function pillTexts(root) {
  return byClass(root, "pill").map((node) => node.textContent);
}

// The view is read-only end to end: the local server has no web-callable
// GitHub write, so nothing inside the view may pretend to act. The one
// sanctioned button is the shared panel chrome's raw-JSON toggle, which
// acts entirely client-side.
function assertNoControls(root) {
  const view = byClass(root, "view-host")[0];
  assert.ok(!allNodes(view).some(
    (node) => (
      ["SELECT", "INPUT"].includes(node.tagName) ||
      (node.tagName === "BUTTON" && !node.classList.contains("raw-toggle"))
    ),
  ));
}

test("a bound project renders binding, installation, access, and sync facts", async (t) => {
  const client = githubClient(boundStatusFixture());
  const { root, mounted } = await mountGithub(t, client);

  // One read, scoped to the picked project through the payload.
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "projects.github_binding.status",
    ),
    {
      function: "projects.github_binding.status",
      payload: { project: "1" },
    },
  );
  assert.deepEqual(panelTitles(root), [
    "This project's repository", "Installation behind this binding",
    "Permissions & automation", "Sync receipts",
  ]);

  const text = viewText(root);
  assert.ok(text.includes("example-org/example-repo"));
  assert.ok(text.includes("main"));
  assert.ok(text.includes("example-org"));
  assert.ok(text.includes("Organization"));
  // Sync facts: the stored mode as read-only text plus the durable receipt.
  assert.ok(text.includes("enabled"));
  assert.ok(text.includes("2026-07-02T08:30:00Z"));
  // The automation reason is a served token rendered as text.
  assert.ok(text.includes("bound"));

  // Served status words render as pills — coloring hints, never invented
  // vocabulary. Automation availability is the one boolean-to-word render.
  const pills = pillTexts(root);
  assert.ok(pills.includes("satisfied"));
  assert.ok(pills.includes("available"));
  assert.ok(pills.includes("success"));

  assertNoControls(root);
  mounted.unmount();
});

test("an unbound project explains what a binding is, with no dead controls", async (t) => {
  const client = githubClient({
    project: "yoke",
    github_repo: "example-org/orphaned-repo",
    default_branch: "",
    github_sync_mode: "backlog_only",
    bound: false,
    binding: null,
    installation: null,
    permission_status: { status: "unknown", missing: [] },
    automation: { available: false, reason: "repo_not_bound" },
  });
  const { root, mounted } = await mountGithub(t, client);

  // No binding means no installation, permission, or sync panels — only
  // the honest explanation.
  assert.deepEqual(panelTitles(root), ["This project's repository"]);
  const text = viewText(root);
  assert.ok(text.includes("A repository binding connects this project"));
  assert.ok(text.includes("This project has no binding."));

  // A project record naming a repo without a binding surfaces as a fact,
  // rendered as copyable code — never a button.
  const view = byClass(root, "view-host")[0];
  const codes = allNodes(view).filter((node) => node.tagName === "CODE");
  assert.deepEqual(
    codes.map((node) => node.textContent), ["example-org/orphaned-repo"],
  );

  assertNoControls(root);
  mounted.unmount();
});

test("a binding without an installation record renders honestly, not a crash", async (t) => {
  const client = githubClient(boundStatusFixture({
    installation: null,
    permission_status: {
      status: "unknown",
      missing: [],
      hint: "Reconnect the GitHub App so Yoke can verify its required " +
        "repository permissions.",
    },
    automation: { available: false, reason: "installation_missing" },
  }));
  const { root, mounted } = await mountGithub(t, client);

  assert.deepEqual(panelTitles(root), [
    "This project's repository", "Installation behind this binding",
    "Permissions & automation", "Sync receipts",
  ]);
  const text = viewText(root);
  // The installation panel names the dangling reference instead of
  // pretending an installation exists.
  assert.ok(text.includes(
    "the binding names installation inst-31, but no installation record " +
      "backs it",
  ));
  // The engine's verdicts render verbatim: the permission hint line and
  // the automation reason token.
  assert.ok(text.includes("Reconnect the GitHub App"));
  assert.ok(text.includes("installation_missing"));
  const pills = pillTexts(root);
  assert.ok(pills.includes("unknown"));
  assert.ok(pills.includes("unavailable"));

  assertNoControls(root);
  mounted.unmount();
});
