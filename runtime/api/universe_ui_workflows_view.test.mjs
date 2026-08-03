import assert from "node:assert/strict";
import test from "node:test";

import {
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  classText,
  mountWorkflows,
  panelTitles,
  workflowFixture,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";

test("Workflows renders the registry as the lifecycle experience", async (t) => {
  const client = workflowsClient();
  const { root, mounted } = await mountWorkflows(t, client);

  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.definition.get",
    ),
    { function: "workflows.definition.get", payload: {} },
  );
  assert.deepEqual(
    panelTitles(root),
    ["Stages", "Execution posture", "Mechanics", "Version history"],
  );
  assert.deepEqual(classText(root, "workflow-tab"), ["Rally"]);
  assert.deepEqual(classText(root, "workflow-stage-label"), [
    "Drafted", "Proving", "Shipped",
  ]);
  assert.deepEqual(classText(root, "workflow-stage-detail-label"), ["Drafted"]);
  assert.equal(byClass(root, "workflow-stage-guide").length, 0);
  assert.deepEqual(classText(root, "workflow-stage-count"), [
    "entry", "1 check",
  ]);
  assert.deepEqual(classText(root, "workflow-detail-row-title"), [
    "CLI", "Harness", "Skill", "Testing", "Approvals", "Delivery",
  ]);
  assert.deepEqual(
    byClass(root, "workflow-posture-label").map(
      (node) => node.children.at(-1)?.textContent,
    ),
    [
      "Ownership", "File Budget", "Path claims", "Worktrees",
      "Parallelism", "Database changes",
    ],
  );
  assert.deepEqual(classText(root, "workflow-home-link"), [
    "QA →", "Inbox →", "Delivery →",
  ]);
  assert.deepEqual(classText(root, "workflow-posture-value"), [
    "one active item claim",
    "required",
    "required",
    "one implementation lane",
    "inside the item only",
    "governed migrations on every change",
  ]);
  assert.deepEqual(classText(root, "workflow-version-title"), [
    "v3 · current", "v1",
  ]);
  assert.deepEqual(classText(root, "workflow-version-description"), [
    "edited here",
    "Readable and eligible to become current again.",
  ]);

  assert.equal(
    allNodes(root).filter((node) => node.tagName === "TABLE").length,
    0,
  );
  assert.equal(byClass(root, "raw-toggle").length, 0);
  assert.equal(byClass(root, "scope-bar").length, 0);
  mounted.unmount();
});

test("Dash entry surfaces use the prototype filing copy", async (t) => {
  const dash = workflowFixture({
    id: "dash",
    name: "Dash",
    currentVersion: 1,
  });
  dash.definition.entry_surfaces = [
    "web_form", "cli", "harness_skill", "promotion",
  ];
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient([dash]),
  );

  assert.deepEqual(
    classText(root, "workflow-detail-row-title").slice(0, 4),
    [
      "Enter a Dash on the web",
      "CLI",
      "Harness",
      "Promote from field note",
    ],
  );
  assert.deepEqual(classText(root, "workflow-entry-command"), [
    'yoke dash "<title>" "<instruction>"',
    '/yoke dash "<instruction>"',
  ]);
  assert.deepEqual(classText(root, "workflow-entry-note"), [
    "agent authors title and files for you",
  ]);
  assert.equal(
    byClass(root, "workflow-entry-note")[0].classList.contains("block"),
    true,
  );
  const newItemLink = byClass(root, "workflow-entry-link")[0];
  assert.equal(newItemLink.href, "#/items/new");
  assert.equal(
    newItemLink.parentNode.classList.contains("workflow-detail-row"),
    true,
  );
  mounted.unmount();
});

test("code-owned workflow revisions do not masquerade as local edits", async (t) => {
  const builtIn = workflowFixture({
    id: "issue",
    name: "Issue",
    currentVersion: 2,
    versions: [
      {
        version: 1,
        definition_digest: "issue-first",
        published_at: "2026-07-20T12:00:00Z",
        published_by_actor_id: null,
      },
      {
        version: 2,
        definition_digest: "issue-current",
        published_at: "2026-07-27T12:00:00Z",
        published_by_actor_id: null,
      },
    ],
  });
  builtIn.source = "built_in";
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient([builtIn]),
  );

  assert.equal(
    classText(root, "workflow-version-description")[0],
    "New items pin this version.",
  );
  mounted.unmount();
});

test("workflows open on the definition's first stage", async (t) => {
  const dash = workflowFixture({
    id: "dash",
    name: "Dash",
    currentVersion: 1,
    stages: [
      { id: "idea", label: "Idea", gates: [] },
      {
        id: "implementing",
        label: "Implementing",
        gates: [{ id: "evidence_check" }],
      },
      { id: "done", label: "Done", gates: [] },
    ],
  });
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient([dash]),
  );

  assert.deepEqual(
    classText(root, "workflow-stage-detail-label"),
    ["idea"],
  );
  assert.equal(
    byClass(root, "workflow-stage")[0].attributes.get("aria-pressed"),
    "true",
  );
  byClass(root, "workflow-stage")[1].dispatchEvent(new Event("click"));
  assert.deepEqual(
    classText(root, "workflow-stage-detail-label"),
    ["implementing"],
  );
  mounted.unmount();
});

test("selecting a stage opens its served description and gate cards", async (t) => {
  const { root, mounted } = await mountWorkflows(t, workflowsClient());
  const proving = byClass(root, "workflow-stage")[1];
  proving.dispatchEvent(new Event("click"));

  assert.deepEqual(
    classText(root, "workflow-stage-description"),
    ["Collect the declared proof."],
  );
  assert.deepEqual(classText(root, "workflow-stage-detail-label"), ["Proving"]);
  assert.deepEqual(classText(root, "workflow-detail-row-title").slice(0, 1), [
    "Evidence check — strict",
  ]);
  assert.deepEqual(classText(root, "workflow-detail-row-description").slice(0, 1), [
    "The declared proof must exist.",
  ]);
  assert.deepEqual(classText(root, "workflow-detail-id").slice(0, 1), [
    "evidence_check",
  ]);
  assert.equal(byClass(root, "workflow-stage")[1].attributes.get("aria-pressed"), "true");
  mounted.unmount();
});

test("disabled workflows remain selectable and render their registry state", async (t) => {
  const workflows = [
    workflowFixture({
      id: "dash",
      name: "Dash",
      currentVersion: 1,
      status: "active",
    }),
    workflowFixture({
      id: "rally",
      name: "Rally",
      currentVersion: 3,
      status: "disabled",
    }),
  ];
  const { documentNode, root, mounted } = await mountWorkflows(
    t, workflowsClient(workflows),
  );

  assert.deepEqual(classText(root, "workflow-tab"), ["Dash", "Rally"]);
  assert.deepEqual(classText(root, "workflow-tab-status"), ["disabled"]);
  assert.equal(
    byClass(root, "workflow-tab")[1].classList.contains("disabled"),
    true,
  );
  assert.equal(
    byClass(root, "workflow-tab")[1].attributes.get("aria-label"),
    "Rally workflow · disabled",
  );

  byClass(root, "workflow-tab")[1].dispatchEvent(new Event("click"));
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.equal(
    byClass(root, "workflow-tab")[1].attributes.get("aria-selected"),
    "true",
  );
  assert.deepEqual(classText(root, "workflow-status"), ["disabled"]);
  assert.deepEqual(classText(root, "workflow-version"), ["current · v3"]);
  mounted.unmount();
});

test("approval summaries use display labels while registry ids stay internal", async (t) => {
  const workflow = workflowFixture();
  workflow.definition.policies.approval_defaults = {
    prove: { roles: ["owner"], actors: [] },
  };
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient([workflow]),
  );

  const descriptions = classText(root, "workflow-detail-row-description");
  assert.ok(descriptions.includes("Proving → project owner"));
  assert.equal(descriptions.includes("prove → project owner"), false);
  mounted.unmount();
});

test("Blitz mechanics link back to Strategy with the prototype skill copy", async (t) => {
  const blitz = workflowFixture({
    id: "blitz",
    name: "Blitz",
    currentVersion: 1,
    skillBindings: [
      {
        skill_id: "refine",
        from_stage_id: "draft",
        through_stage_id: "prove",
      },
      {
        skill_id: "blitz",
        from_stage_id: "prove",
        through_stage_id: "ship",
      },
    ],
  });
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient([blitz]),
  );

  assert.ok(classText(root, "workflow-detail-row-description").includes(
    "Run /yoke refine then /yoke blitz in a supported harness like Claude " +
    "Code or Codex — blitz executes the linked document directly, in " +
    "continuous slices; nothing is copied.",
  ));
  assert.equal(
    byClass(root, "workflow-home-link").find(
      (node) => node.textContent === "Strategy →",
    )?.href,
    "#/strategy",
  );
  mounted.unmount();
});

test("built-in skill copy follows the served binding signature", async (t) => {
  const dash = workflowFixture({
    id: "dash",
    name: "Dash",
    currentVersion: 1,
    skillBindings: [{
      skill_id: "alternate",
      from_stage_id: "draft",
      through_stage_id: "ship",
    }],
  });
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient([dash]),
  );

  const descriptions = classText(root, "workflow-detail-row-description");
  assert.ok(descriptions.includes(
    "Run /yoke alternate in a supported harness.",
  ));
  assert.equal(descriptions.some((copy) => copy.includes(
    "it runs the whole item: survey, worktree, execute, verify, merge, evidence",
  )), false);
  mounted.unmount();
});
