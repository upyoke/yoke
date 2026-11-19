// An org admin's controls for a person's direct project grants: change the
// role on a project, remove it, or add access to another project. Each change
// calls actors.project_role.set or .remove and reloads the roster; a refusal
// names its reason and leaves the controls as they were.

import { actorIsOwner, callerIsOwner } from "./actor_role_control.js";
import { callFunction, el } from "./universe_view_support.js";

async function change(roster, feedback, reload, functionId, payload, controls, pending) {
  for (const control of controls) control.disabled = true;
  feedback.textContent = pending;
  try {
    const done = await callFunction(roster.client, functionId, payload);
    if (done.status === 200 && done.envelope?.success) {
      await reload();
      return true;
    }
    feedback.textContent = done.envelope?.error?.message || "Project access change failed; retry.";
  } catch (error) {
    feedback.textContent = `${error}; retry the change.`;
  }
  for (const control of controls) control.disabled = false;
  return false;
}

function choice(documentNode, values, current, label) {
  const select = el(documentNode, "select", "actors-role-select");
  select.setAttribute("aria-label", label);
  const shown = current && !values.some((value) => value.value === current)
    ? [{ value: current, label: current, disabled: true }, ...values] : values;
  for (const value of shown) {
    const option = el(documentNode, "option", null, value.label);
    option.value = value.value;
    option.disabled = Boolean(value.disabled);
    select.appendChild(option);
  }
  select.value = current;
  return select;
}

function button(documentNode, label) {
  const node = el(documentNode, "button", "item-button", label);
  node.type = "button";
  return node;
}

// `roster.projects` lists the projects the caller may grant; a server that
// does not yet send it offers change and remove but no Add.
export function projectAccessControls(documentNode, actor, roster, feedback, reload) {
  const cell = el(documentNode, "td");
  const roles = roster.person_org_roles
    .filter((role) => role !== "owner" || callerIsOwner(roster))
    .map((role) => ({ value: role, label: role }));
  const locked = actorIsOwner(actor) && !callerIsOwner(roster);
  for (const grant of actor.roles?.org || []) {
    const access = el(documentNode, "span", "actors-access");
    access.appendChild(el(documentNode, "b", null, "All projects"));
    access.appendChild(el(documentNode, "span", "actors-muted", ` · from org ${grant.role}`));
    cell.appendChild(access);
  }
  for (const grant of actor.roles?.projects || []) {
    const access = el(documentNode, "div", "actors-access");
    access.appendChild(el(documentNode, "span", null, `${grant.project} · `));
    const select = choice(documentNode, roles, grant.role, `Role on ${grant.project} for ${actor.name}`);
    const remove = button(documentNode, "Remove");
    remove.setAttribute("aria-label", `Remove ${actor.name}'s access to ${grant.project}`);
    select.disabled = remove.disabled = locked;
    select.addEventListener("change", async () => {
      const done = await change(roster, feedback, reload, "actors.project_role.set", {
        actor_id: actor.id, project: grant.project, role: select.value,
      }, [select, remove], `Changing ${actor.name}'s role on ${grant.project} to ${select.value}…`);
      if (!done) select.value = grant.role;
    });
    remove.addEventListener("click", () => change(roster, feedback, reload, "actors.project_role.remove", {
      actor_id: actor.id, project: grant.project,
    }, [select, remove], `Removing ${actor.name}'s access to ${grant.project}…`));
    access.appendChild(select);
    access.appendChild(remove);
    cell.appendChild(access);
  }
  const granted = new Set((actor.roles?.projects || []).map((grant) => grant.project));
  const open = (Array.isArray(roster.projects) ? roster.projects : [])
    .filter((project) => !granted.has(project.slug))
    .map((project) => ({ value: project.slug, label: project.name || project.slug }));
  if (open.length && !locked) {
    const add = el(documentNode, "div", "actors-project-add");
    const project = choice(documentNode, open, open[0].value, `Project to add for ${actor.name}`);
    const fallback = roles.some((role) => role.value === "viewer") ? "viewer" : roles[0]?.value || "";
    const role = choice(documentNode, roles, fallback, `Role to add for ${actor.name}`);
    const submit = button(documentNode, "Add project access");
    submit.setAttribute("aria-label", `Add project access for ${actor.name}`);
    submit.addEventListener("click", () => change(roster, feedback, reload, "actors.project_role.set", {
      actor_id: actor.id, project: project.value, role: role.value,
    }, [project, role, submit], `Adding ${actor.name} to ${project.value} as ${role.value}…`));
    add.appendChild(project);
    add.appendChild(role);
    add.appendChild(submit);
    cell.appendChild(add);
  }
  if (!cell.children.length) cell.appendChild(el(documentNode, "span", "actors-muted", "—"));
  return cell;
}
