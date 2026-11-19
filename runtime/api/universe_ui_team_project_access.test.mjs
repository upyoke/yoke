import assert from "node:assert/strict";
import test from "node:test";

import { renderTeamView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_team.js";
import { FakeDocument, allNodes, settle } from "./universe_ui_dom_test_support.mjs";

const PERSON_ROLES = ["owner", "admin", "operator", "viewer"];
const PROJECTS = [{ slug: "platform", name: "Platform" }, { slug: "yoke", name: "Yoke" }];

function person(org, projects, overrides = {}) {
  return {
    id: 400, kind: "human", name: "Testy", status: "active", tokens: [],
    roles: { org: org.map((role) => ({ org: "Test", role })), projects },
    identity: { email: "testy@example.test" }, ...overrides,
  };
}

function admin() {
  return person(["admin"], [], { id: 1, name: "Admin" });
}

function roster(target, extra = {}) {
  return {
    current_actor_id: 1, can_manage_actors: true, person_org_roles: PERSON_ROLES,
    projects: PROJECTS, rows: [admin(), target], ...extra,
  };
}

function fixture(rosters, answer = () => ({ success: true, result: {} })) {
  const document = new FakeDocument();
  const main = document.createElement("main");
  const calls = [];
  const context = {
    document, capabilities: { portability_mode: "hosted" },
    screenPreferences: {
      sortFor: () => null, refreshSortFor: async () => "", saveSortFor: () => Promise.resolve(""),
    },
    isMounted: () => true,
    client: {
      async call(request) {
        calls.push(request);
        if (request.function === "actors.roster") {
          return { status: 200, envelope: { success: true, result: rosters.length > 1 ? rosters.shift() : rosters[0] } };
        }
        return { status: 200, envelope: answer(request) };
      },
    },
  };
  return { context, main, calls };
}

const labelled = (main, label) => allNodes(main).find((node) => node.getAttribute?.("aria-label") === label);
const mutations = (calls) => calls.filter((call) => call.function !== "actors.roster"
  && call.function.startsWith("actors."));

test("an admin adds project access with a project and role, then the roster reloads", async () => {
  const before = roster(person([], []));
  const after = roster(person([], [{ project: "yoke", name: "Yoke", role: "viewer" }]));
  const { context, main, calls } = fixture([before, after]);
  await renderTeamView(context, main);
  const project = labelled(main, "Project to add for Testy");
  assert.deepEqual(project.children.map((option) => option.value), ["platform", "yoke"]);
  assert.equal(labelled(main, "Role to add for Testy").value, "viewer");
  project.value = "yoke";
  labelled(main, "Add project access for Testy").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(mutations(calls), [{
    function: "actors.project_role.set", payload: { actor_id: 400, project: "yoke", role: "viewer" },
  }]);
  assert.equal(labelled(main, "Role on yoke for Testy").value, "viewer");
  assert.deepEqual(labelled(main, "Project to add for Testy").children.map((option) => option.value), ["platform"]);
});

test("an admin changes and removes a direct project grant", async () => {
  const granted = roster(person(["viewer"], [{ project: "yoke", name: "Yoke", role: "viewer" }]));
  const { context, main, calls } = fixture([granted, granted, granted]);
  await renderTeamView(context, main);
  const select = labelled(main, "Role on yoke for Testy");
  select.value = "operator";
  select.dispatchEvent(new Event("change"));
  await settle();
  labelled(main, "Remove Testy's access to yoke").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(mutations(calls), [
    { function: "actors.project_role.set", payload: { actor_id: 400, project: "yoke", role: "operator" } },
    { function: "actors.project_role.remove", payload: { actor_id: 400, project: "yoke" } },
  ]);
});

test("a refused project change names the reason and restores the role", async () => {
  const granted = roster(person([], [{ project: "yoke", name: "Yoke", role: "viewer" }]));
  const { context, main } = fixture([granted], () => ({
    success: false, error: { code: "last_owner", message: "last_owner: this change would remove the last active human owner" },
  }));
  await renderTeamView(context, main);
  const select = labelled(main, "Role on yoke for Testy");
  select.value = "operator";
  select.dispatchEvent(new Event("change"));
  await settle();
  assert.match(main.textContent, /last active human owner/);
  assert.equal(select.value, "viewer");
  assert.equal(select.disabled, false);
});

test("No org role removes the org role; a person without one shows it selected", async () => {
  const before = roster(person(["operator"], [{ project: "yoke", name: "Yoke", role: "viewer" }]));
  const after = roster(person([], [{ project: "yoke", name: "Yoke", role: "viewer" }]));
  const { context, main, calls } = fixture([before, after]);
  await renderTeamView(context, main);
  const select = labelled(main, "Org role for Testy");
  assert.equal(select.children.at(-1).textContent, "No org role");
  select.value = "none";
  select.dispatchEvent(new Event("change"));
  await settle();
  assert.deepEqual(mutations(calls), [{ function: "actors.role.remove", payload: { actor_id: 400 } }]);
  assert.equal(labelled(main, "Org role for Testy").value, "none");
  assert.doesNotMatch(labelled(main, "Org role for Testy").parentNode.parentNode.textContent, /All projects/);
});

test("an older roster without projects offers change and remove but no Add", async () => {
  const granted = roster(person([], [{ project: "yoke", name: "Yoke", role: "viewer" }]), { projects: undefined });
  const { context, main } = fixture([granted]);
  await renderTeamView(context, main);
  assert.ok(labelled(main, "Role on yoke for Testy"));
  assert.equal(labelled(main, "Add project access for Testy"), undefined);
});

test("a non-owner admin cannot change an owner's project access", async () => {
  const owner = roster(person([], [{ project: "yoke", name: "Yoke", role: "owner" }]));
  const { context, main } = fixture([owner]);
  await renderTeamView(context, main);
  assert.equal(labelled(main, "Role on yoke for Testy").disabled, true);
  assert.equal(labelled(main, "Remove Testy's access to yoke").disabled, true);
  assert.equal(labelled(main, "Add project access for Testy"), undefined);
});
