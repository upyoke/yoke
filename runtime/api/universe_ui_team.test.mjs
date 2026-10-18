import assert from "node:assert/strict";
import test from "node:test";

import { renderTeamView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_team.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

function actor(status, tokens = [], overrides = {}) {
  return {
    id: 2, kind: "human", name: "Member", status, tokens,
    roles: { org: [{ org: "Test", role: "operator" }], projects: [] },
    identity: { email: "member@example.test" },
    ...overrides,
  };
}

function preferences(saved = null) {
  const saves = [];
  let sort = saved;
  return {
    saves,
    sortFor: (viewId) => (viewId === "actors" ? sort : null),
    refreshSortFor: async () => "",
    saveSortFor: (viewId, chosen) => { saves.push([viewId, chosen]); sort = chosen; return Promise.resolve(""); },
  };
}

function fixture(rosters, screenPreferences) {
  const document = new FakeDocument();
  const main = document.createElement("main");
  const calls = [];
  const context = {
    document, capabilities: { portability_mode: "hosted" }, screenPreferences,
    isMounted: () => true,
    client: {
      async call(request) {
        calls.push(request);
        const result = request.function === "actors.roster"
          ? rosters.shift() : { actor_id: 2, status: "active", revoked_tokens: 0 };
        return { status: 200, envelope: { success: true, result } };
      },
    },
  };
  return { context, main, calls };
}

const button = (main, text) => allNodes(main).find((node) => node.tagName === "BUTTON" && node.textContent === text);
const names = (main) => byClass(main, "actors-name").map((node) => node.textContent);

test("disabled actors are hidden behind a counted toggle that survives an enable", async () => {
  const initial = {
    current_actor_id: 1, can_manage_actors: true,
    rows: [actor("disabled", [{
      token_id: 42, name: "machine", last_used_at: "never",
      machine_id: "machine-a", machine_name: "Office",
    }]), actor("active", [], { id: 3, name: "Other" })],
  };
  const refreshed = {
    current_actor_id: 1, can_manage_actors: true,
    rows: [actor("active"), actor("active", [], { id: 3, name: "Other" })],
  };
  const { context, main, calls } = fixture([initial, refreshed]);
  await renderTeamView(context, main);
  assert.deepEqual(names(main), ["Other"]);
  assert.match(main.textContent, /Show disabled \(1\)/);
  const toggle = allNodes(main).find((node) => node.tagName === "INPUT" && node.type === "checkbox");
  assert.equal(toggle.checked, false);
  toggle.checked = true;
  toggle.dispatchEvent(new Event("change"));
  assert.deepEqual(names(main), ["Member", "Other"]);
  assert.match(main.textContent, /machine \(#42\)/);
  assert.match(main.textContent, /Office/);
  assert.doesNotMatch(main.textContent, /reconnect affected machines/);
  button(main, "Enable").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(calls[1], {
    function: "actors.state.set", payload: { actor_id: 2, enabled: true },
  });
  assert.equal(calls[2].function, "actors.roster");
  assert.deepEqual(names(main), ["Member", "Other"]);
  assert.doesNotMatch(main.textContent, /Show disabled/);
});

test("Team renders an empty roster without stale controls", async () => {
  const { context, main } = fixture([{
    current_actor_id: 1, can_manage_actors: false, rows: [],
  }]);
  await renderTeamView(context, main);
  assert.match(main.textContent, /No actors are registered/);
  assert.equal(allNodes(main).filter((node) => node.tagName === "BUTTON").length, 0);
});

test("disabling names the actor and requires confirmation, with cancel and retry", async () => {
  const roster = { current_actor_id: 1, can_manage_actors: true, rows: [actor("active")] };
  const { context, main, calls } = fixture([roster, roster]);
  const original = context.client.call;
  let attempts = 0;
  context.client.call = async (request) => {
    if (request.function === "actors.state.set" && ++attempts === 1) {
      return { status: 503, envelope: { success: false, error: { message: "Unavailable" } } };
    }
    return original(request);
  };
  await renderTeamView(context, main);
  button(main, "Disable").dispatchEvent(new Event("click"));
  assert.match(main.textContent, /Disable Member\? Their API keys will be revoked\./);
  assert.equal(attempts, 0);
  button(main, "Cancel").dispatchEvent(new Event("click"));
  assert.equal(attempts, 0);
  button(main, "Disable").dispatchEvent(new Event("click"));
  button(main, "Disable Member").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(button(main, "Disable Member").disabled, false);
  assert.match(main.textContent, /Unavailable/);
  button(main, "Disable Member").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(attempts, 2);
  assert.deepEqual(calls.find((call) => call.function === "actors.state.set").payload, { actor_id: 2, enabled: false });
});

test("columns sort through the shared header and save under the actors roster preference", async () => {
  const roster = {
    current_actor_id: 1, can_manage_actors: false,
    rows: [
      actor("active", [], { id: 4, name: "beta", identity: { email: "a@example.test" } }),
      actor("active", [], { id: 5, name: "Alpha", identity: { email: "z@example.test" } }),
    ],
  };
  const saved = preferences({ column: "email", direction: "desc" });
  const { context, main } = fixture([roster], saved);
  await renderTeamView(context, main);
  assert.deepEqual(names(main), ["Alpha", "beta"]);
  const actorSort = () => allNodes(main).find((node) => node.getAttribute?.("data-sort-column") === "name");
  actorSort().dispatchEvent(new Event("click"));
  assert.deepEqual(names(main), ["Alpha", "beta"]);
  assert.deepEqual(saved.saves, [["actors", { column: "name", direction: "asc" }]]);
  actorSort().dispatchEvent(new Event("click"));
  assert.deepEqual(names(main), ["beta", "Alpha"]);
  assert.deepEqual(saved.saves[1], ["actors", { column: "name", direction: "desc" }]);
});

test("a server that does not save the actors sort keeps the header sort without a retry prompt", async () => {
  const { createProjectSelection } = await import("../../packages/yoke-core/src/yoke_core/ui/static/universe_project_selection.js");
  const writes = [];
  const store = createProjectSelection(() => {}, null, (viewId, sort) => { writes.push([viewId, sort]); });
  const olderServer = async () => ({ views: {}, sorts: { items: { column: "title", direction: "asc" } } });
  assert.equal(await store.refreshSortFor("actors", olderServer), "");
  const roster = {
    current_actor_id: 1, can_manage_actors: false,
    rows: [actor("active", [], { id: 4, name: "beta" }), actor("active", [], { id: 5, name: "Alpha" })],
  };
  const { context, main } = fixture([roster], store);
  context.client.call = async (request) => ({
    status: 200, envelope: { success: true, result: request.function === "actors.roster" ? roster : await olderServer() },
  });
  await renderTeamView(context, main);
  allNodes(main).find((node) => node.getAttribute?.("data-sort-column") === "name").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(names(main), ["beta", "Alpha"]);
  assert.deepEqual(writes, []);
  assert.match(main.textContent, /does not save this page's sort; it applies until you leave the page/);
  assert.doesNotMatch(main.textContent, /retry/);
});

const PERSON_ROLES = ["admin", "operator", "viewer"];
const roleSelect = (main) => allNodes(main).find((node) => node.tagName === "SELECT");
const manageableRoster = (rows = [actor("active")]) => ({
  current_actor_id: 1, can_manage_actors: true, person_org_roles: PERSON_ROLES, rows,
});

test("an org admin changes a person's one org role and the roster reloads", async () => {
  const roster = manageableRoster();
  const promoted = { ...roster, rows: [actor("active", [], {
    roles: { org: [{ org: "Test", role: "admin" }], projects: [] },
  })] };
  const { context, main, calls } = fixture([roster, promoted], preferences());
  await renderTeamView(context, main);
  const select = roleSelect(main);
  assert.equal(select.value, "operator");
  assert.deepEqual(select.children.map((option) => option.value), PERSON_ROLES);
  select.value = "admin";
  select.dispatchEvent(new Event("change"));
  await settle();
  assert.deepEqual(calls[1], {
    function: "actors.role.set", payload: { actor_id: 2, role: "admin" },
  });
  assert.equal(calls[2].function, "actors.roster");
  assert.equal(roleSelect(main).value, "admin");
});

test("a refused role change names the reason and restores the current role", async () => {
  const roster = manageableRoster();
  const { context, main } = fixture([roster], preferences());
  const original = context.client.call;
  context.client.call = async (request) => (
    request.function === "actors.roster" ? original(request) : {
      status: 200,
      envelope: { success: false, error: { message: "actor 2 is the last active admin of the org" } },
    }
  );
  await renderTeamView(context, main);
  const select = roleSelect(main);
  select.value = "viewer";
  select.dispatchEvent(new Event("change"));
  await settle();
  assert.match(main.textContent, /last active admin/);
  assert.equal(select.value, "operator");
  assert.equal(select.disabled, false);
});

test("an older server without person_org_roles shows every org grant read-only", async () => {
  const { context, main } = fixture([{
    current_actor_id: 1, can_manage_actors: true,
    rows: [actor("active", [], {
      roles: { org: [{ org: "Test", role: "admin" }, { org: "Test", role: "operator" }], projects: [] },
    })],
  }], preferences());
  await renderTeamView(context, main);
  assert.equal(roleSelect(main), undefined);
  assert.match(main.textContent, /admin/);
  assert.match(main.textContent, /operator/);
});

test("a person still holding several org roles shows them and asks for one", async () => {
  const roster = manageableRoster([actor("active", [], {
    roles: { org: [{ org: "Test", role: "admin" }, { org: "Test", role: "operator" }], projects: [] },
  })]);
  const { context, main } = fixture([roster], preferences());
  await renderTeamView(context, main);
  const select = roleSelect(main);
  assert.equal(select.value, "");
  assert.equal(select.children[0].textContent, "admin, operator");
  assert.equal(select.children[0].disabled, true);
});

const GRANT_ROSTER_FIELDS = {
  role_descriptions: {
    deployment_ci: "Trigger deployments.", hosted_service: "Deliver hosted lifecycle.",
    migration_verification_ci: "Verify migration content.", owner: "Project admin.",
  },
  machine_only_roles: ["deployment_ci", "hosted_service", "migration_verification_ci"],
  bootstrap_only_roles: ["hosted_service"],
};
const machine = (id, name, org, projects) => actor("active", [], {
  id, name, kind: "system", identity: null,
  roles: { org: org.map((role) => ({ org: "Test", role })), projects },
});
const MACHINES = [
  machine(169, "release-bridge", ["migration_verification_ci"], [{ project: "yoke", role: "deployment_ci" }]),
  machine(367, "hosted_service", ["hosted_service"], []),
];
const grantTexts = (main) => byClass(main, "actors-grant").map((node) => node.textContent);

test("machine grants name scope, role, how it is held and what it allows", async () => {
  const { context, main } = fixture([{ current_actor_id: 1, rows: MACHINES, ...GRANT_ROSTER_FIELDS }], preferences());
  await renderTeamView(context, main);
  assert.deepEqual(grantTexts(main), [
    "Orghosted_servicemachine-onlybootstrap-grantedDeliver hosted lifecycle.",
    "Orgmigration_verification_cimachine-onlyVerify migration content.",
    "Project · yokedeployment_cimachine-onlyTrigger deployments.",
  ]);
  assert.equal(byClass(main, "actors-grants").flatMap((cell) => byClass(cell, "idle")).length, 0);
});

test("an older server's roster still lists each grant's scope and role", async () => {
  for (const missing of [...Object.keys(GRANT_ROSTER_FIELDS), "all"]) {
    const fields = missing === "all" ? {} : { ...GRANT_ROSTER_FIELDS, [missing]: undefined };
    const { context, main } = fixture([{ current_actor_id: 1, rows: MACHINES, ...fields }], preferences());
    await renderTeamView(context, main);
    const [hosted, verify, deploy] = grantTexts(main);
    assert.ok(deploy.startsWith("Project · yokedeployment_ci"), missing);
    assert.equal(hosted.includes("bootstrap-granted"), !["bootstrap_only_roles", "all"].includes(missing));
    assert.equal(verify.includes("machine-only"), !["machine_only_roles", "all"].includes(missing));
    assert.equal(verify.includes("Verify migration content."), !["role_descriptions", "all"].includes(missing));
  }
});

test("every org role reaches all projects and project grants read as roles", async () => {
  const person = (id, org, projects = []) => actor("active", [], {
    id, name: `Person ${id}`, roles: { org: org.map((role) => ({ org: "Test", role })), projects },
  });
  const { context, main } = fixture([{
    current_actor_id: 1, ...GRANT_ROSTER_FIELDS,
    rows: [person(334, ["operator"]), person(5, ["viewer"], [{ project: "yoke", role: "owner" }]), person(6, [])],
  }], preferences());
  await renderTeamView(context, main);
  const access = allNodes(main).filter((node) => node.getAttribute?.("data-label") === "Project access")
    .map((cell) => cell.textContent);
  assert.deepEqual(access, ["All projects · from org vieweryoke · owner", "—", "All projects · from org operator"]);
  assert.equal(byClass(main, "actors-role")[0].title, "Project admin.");
});

test("grants sort machine accounts and an unknown saved column falls back to name", async () => {
  const rows = [machine(2, "zeta", ["migration_verification_ci"], []), machine(3, "alpha", [], [])];
  const sorted = fixture([{ current_actor_id: 1, rows }], preferences({ column: "grants", direction: "desc" }));
  await renderTeamView(sorted.context, sorted.main);
  assert.deepEqual(names(sorted.main), ["zeta", "alpha"]);
  const stale = fixture([{ current_actor_id: 1, rows }], preferences({ column: "retired", direction: "asc" }));
  await renderTeamView(stale.context, stale.main);
  assert.deepEqual(names(stale.main), ["alpha", "zeta"]);
});
