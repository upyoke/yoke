import assert from "node:assert/strict";
import test from "node:test";
import { roleControl } from "../../packages/yoke-core/src/yoke_core/ui/static/actor_role_control.js";
import { FakeDocument, allNodes } from "./universe_ui_dom_test_support.mjs";

const roles = ["owner", "admin", "operator", "viewer"];
function render(callerRole, targetRole) {
  const document = new FakeDocument();
  const caller = { id: 1, kind: "human", status: "active", roles: { org: [{ role: callerRole }] } };
  const target = { id: 2, kind: "human", status: "active", name: "Teammate", roles: { org: [{ role: targetRole }] } };
  const roster = { current_actor_id: 1, rows: [caller, target] };
  return roleControl(document, target, roles, roster, { textContent: "" }, () => {});
}

test("admins see owner grants read-only and cannot choose owner for a teammate", () => {
  assert.equal(render("admin", "owner").disabled, true);
  const select = render("admin", "operator");
  assert.deepEqual(allNodes(select).filter((node) => node.tagName === "OPTION").map((node) => node.value), ["admin", "operator", "viewer"]);
});

test("owners can choose all four human roles and edit owner grants", () => {
  const select = render("owner", "owner");
  assert.equal(select.disabled, false);
  assert.deepEqual(allNodes(select).filter((node) => node.tagName === "OPTION").map((node) => node.value), roles);
});
