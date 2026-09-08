// One machine's identity, access, credentials, harness health, and history.

import {
  callFunction, el, loadScopedSection, section,
} from "./universe_view_support.js";
import { presentSessionControlFailure } from "./universe_session_control_data.js";
import { LAUNCHABLE_SURFACES } from "./universe_machines_panel.js";
import {
  hookTrustRemediation,
} from "./universe_views_overview_activation_copy.js";
import { readingIsStale } from "./universe_machines_meters.js";

function fact(documentNode, label, value) {
  const row = el(documentNode, "div", "machine-detail-fact");
  row.appendChild(el(documentNode, "span", null, label));
  row.appendChild(el(documentNode, "strong", null, String(value ?? "—")));
  return row;
}

function detailCard(documentNode, title) {
  const card = el(documentNode, "section", "machine-detail-card");
  card.appendChild(el(documentNode, "h3", null, title));
  return card;
}

function appendAbout(documentNode, host, result) {
  const machine = result.machine;
  const relay = result.relay || {};
  const card = detailCard(documentNode, "About");
  card.appendChild(fact(documentNode, "Name", machine.name));
  card.appendChild(fact(documentNode, "Machine id", machine.machine_id));
  card.appendChild(fact(documentNode, "Owner", machine.owner));
  card.appendChild(fact(documentNode, "Registered", machine.registered_at));
  card.appendChild(fact(
    documentNode, "Last seen", relay.last_seen_at || machine.last_seen_at,
  ));
  card.appendChild(fact(documentNode, "Relay", relay.liveness || "not seen"));
  card.appendChild(fact(documentNode, "Relay version", relay.relay_version));
  card.appendChild(fact(documentNode, "Token", result.token.status));
  card.appendChild(fact(documentNode, "Token created", result.token.created_at));
  card.appendChild(fact(documentNode, "Token last used", result.token.last_used_at));
  host.appendChild(card);
}

function planObservation(reading) {
  const windows = Array.isArray(reading?.windows) ? reading.windows : [];
  return {
    stale: Boolean(reading) && readingIsStale(reading.observed_at),
    readable: windows.some((window) => window?.status === "ok"),
    reason: windows.find(
      (window) => window?.status !== "ok" && window?.reason,
    )?.reason,
  };
}

function harnessCredentialLabel(presence, surface, reading) {
  if (!Object.hasOwn(presence, surface)) return null;
  if (!presence[surface]) return "credential presence not reported";
  const observation = planObservation(reading);
  return observation.stale || !observation.readable
    ? "credential observation not current"
    : "credential present";
}

function appendCredentials(documentNode, host, presence, planLimits) {
  const card = detailCard(documentNode, "Credential presence");
  card.appendChild(fact(
    documentNode, "GitHub", presence.github ? "present" : "not reported",
  ));
  card.appendChild(fact(
    documentNode, "AWS", presence.aws ? "present" : "not reported",
  ));
  for (const surface of Object.keys(presence.harnesses || {})) {
    card.appendChild(fact(
      documentNode,
      surface,
      harnessCredentialLabel(presence.harnesses, surface, planLimits[surface]),
    ));
  }
  host.appendChild(card);
}

function surfaceControl(documentNode, context, result, harness, reload, status) {
  const row = el(documentNode, "div", "machine-harness-row");
  const copy = el(documentNode, "div");
  copy.appendChild(el(documentNode, "strong", null, harness.label));
  const reading = result.relay?.plan_limits?.[harness.key];
  const observation = planObservation(reading);
  const plan = observation.readable && !observation.stale
    ? reading.plan_tier
    : null;
  const harnessPresence = result.credential_presence?.harnesses || {};
  const credential = harnessCredentialLabel(
    harnessPresence, harness.key, reading,
  );
  copy.appendChild(el(
    documentNode,
    "span",
    "machine-detail-muted",
    [
      harness.version,
      plan,
      credential,
      observation.stale ? "plan observation stale" : null,
      observation.reason ? `plan limit ${observation.reason}` : null,
      harness.status,
      harness.last_seen_at,
    ]
      .filter(Boolean).join(" · "),
  ));
  row.appendChild(copy);
  if (!LAUNCHABLE_SURFACES.includes(harness.key)) return row;
  const project = result.projects[0]?.slug;
  const mark = result.surface_policies.find((entry) => entry.surface === harness.key);
  const button = el(
    documentNode, "button", "item-button", mark ? "Enable" : "Disable",
  );
  button.type = "button";
  button.disabled = !project || Boolean(result.machine.retired_at);
  button.addEventListener("click", async () => {
    const functionId = mark
      ? "session_control.surface_policy.enable"
      : "session_control.surface_policy.disable";
    const payload = {
      project,
      machine_id: result.machine.machine_id,
      surface: harness.key,
    };
    if (!mark) {
      const reason = documentNode.defaultView.prompt("Why disable this surface?");
      if (!reason) return;
      payload.reason = reason;
    }
    const response = await callFunction(context.client, functionId, payload);
    if (!response.envelope.success) {
      status.textContent = presentSessionControlFailure(
        response, "The surface policy could not be changed.",
      );
      return;
    }
    reload();
  });
  row.appendChild(button);
  return row;
}

function appendHarnesses(documentNode, host, context, result, reload, status) {
  const card = detailCard(documentNode, "Harnesses");
  for (const harness of result.harnesses || []) {
    card.appendChild(surfaceControl(
      documentNode, context, result, harness, reload, status,
    ));
  }
  host.appendChild(card);
}

function appendProjects(documentNode, host, projects) {
  const card = detailCard(documentNode, "Projects");
  if (!projects.length) card.appendChild(el(
    documentNode,
    "p",
    "machine-detail-muted",
    "No visible checkout has reported.",
  ));
  for (const project of projects) {
    const block = el(documentNode, "div", "machine-project-row");
    block.appendChild(el(documentNode, "strong", null, project.name));
    block.appendChild(el(
      documentNode,
      "code",
      null,
      project.checkout || "Checkout path not reported",
    ));
    const statuses = (project.hook_reports || []).map(
      (row) => `${row.harness_id}: ${row.approval_state}`,
    );
    block.appendChild(el(
      documentNode,
      "span",
      "machine-detail-muted",
      statuses.join(" · ") || "Hook health not reported",
    ));
    for (const report of project.hook_reports || []) {
      if (report.approval_state !== "unapproved" || !report.trust_surface) continue;
      block.appendChild(el(
        documentNode,
        "span",
        "machine-detail-muted",
        hookTrustRemediation(report.trust_surface),
      ));
    }
    block.appendChild(el(documentNode, "span", null, project.recovery));
    card.appendChild(block);
  }
  host.appendChild(card);
}

function appendHistory(documentNode, host, title, rows, label) {
  const card = detailCard(documentNode, title);
  if (!rows.length) card.appendChild(el(
    documentNode, "p", "machine-detail-muted", "None",
  ));
  for (const row of rows.slice(0, 10)) {
    card.appendChild(fact(
      documentNode,
      label(row),
      [row.state || row.mode, row.result_code, row.created_at || row.offered_at]
        .filter(Boolean).join(" · "),
    ));
  }
  host.appendChild(card);
}

function appendAccess(documentNode, host, context, result, reload, status) {
  const card = detailCard(documentNode, "Machine access");
  const select = el(documentNode, "select", "machine-access-select");
  const currentMode = result.machine.access?.use?.mode;
  for (const mode of ["owner_only", "actors", "project_role", "universe"]) {
    const option = el(documentNode, "option", null, mode.replaceAll("_", " "));
    option.value = mode;
    option.selected = currentMode === mode;
    select.appendChild(option);
  }
  const actors = el(documentNode, "input", "machine-access-input");
  actors.placeholder = "Actor IDs, comma-separated";
  actors.value = (result.machine.access?.use?.actor_ids || []).join(", ");
  const project = el(documentNode, "input", "machine-access-input");
  project.placeholder = "Project ID";
  project.value = result.machine.access?.use?.project_id || "";
  const role = el(documentNode, "input", "machine-access-input");
  role.placeholder = "Project role";
  role.value = result.machine.access?.use?.role || "";
  const retired = Boolean(result.machine.retired_at);
  for (const input of [select, actors, project, role]) input.disabled = retired;
  const save = el(documentNode, "button", "item-button", "Save access");
  save.type = "button";
  save.disabled = retired;
  save.addEventListener("click", async () => {
    const settings = [];
    if (select.value === "actors") settings.push([
      "use.actor_ids",
      actors.value.split(",").map((value) => Number(value.trim())).filter(
        (value) => Number.isInteger(value) && value > 0,
      ),
    ]);
    if (select.value === "project_role") settings.push(
      ["use.project_id", Number(project.value)],
      ["use.role", role.value.trim()],
    );
    settings.push(["use.mode", select.value]);
    for (const [path, value] of settings) {
      const response = await callFunction(context.client, "machine.settings.set", {
        machine_id: result.machine.machine_id, path, value,
      });
      if (!response.envelope.success) {
        status.textContent = presentSessionControlFailure(
          response, "Machine access could not be changed.",
        );
        return;
      }
    }
    reload();
  });
  card.appendChild(select);
  card.appendChild(actors);
  card.appendChild(project);
  card.appendChild(role);
  card.appendChild(save);
  host.appendChild(card);
}

function appendRetirement(documentNode, grid, context, result, reload, status) {
  if (result.machine.retired_at) return;
  const retire = detailCard(documentNode, "Retire machine");
  retire.appendChild(el(
    documentNode,
    "p",
    "machine-detail-muted",
    "Revokes only this machine's bearer. History and account access remain.",
  ));
  const button = el(
    documentNode, "button", "item-button machine-retire", "Retire",
  );
  button.type = "button";
  button.addEventListener("click", async () => {
    if (!documentNode.defaultView.confirm("Retire this machine?")) return;
    const response = await callFunction(context.client, "machine.retire", {
      machine_id: result.machine.machine_id,
    });
    if (!response.envelope.success) {
      status.textContent = presentSessionControlFailure(
        response, "The machine could not be retired.",
      );
      return;
    }
    reload();
  });
  retire.appendChild(button);
  grid.appendChild(retire);
}

export function renderMachineDetail(context, main, _project, detail, navigation = {}) {
  const documentNode = context.document;
  const status = el(documentNode, "p", "sessions-action-status");
  const panel = section(documentNode, "Machine");
  main.replaceChildren(status, panel);
  const load = () => loadScopedSection(
    context,
    panel,
    [{ functionId: "machine.detail", payload: { machine_id: detail } }],
    (body, calls) => {
      const result = calls[0].envelope.result;
      navigation.setTitle?.(result.machine.name);
      status.textContent = result.machine.retired_at
        ? "Retired — its bearer is revoked; sessions and launches remain as history."
        : "Registered machine";
      const grid = el(documentNode, "div", "machine-detail-grid");
      appendAbout(documentNode, grid, result);
      appendCredentials(
        documentNode,
        grid,
        result.credential_presence || {},
        result.relay?.plan_limits || {},
      );
      appendHarnesses(documentNode, grid, context, result, load, status);
      appendProjects(documentNode, grid, result.projects || []);
      appendHistory(
        documentNode, grid, "Running now", result.running_sessions || [],
        (row) => row.surface || row.executor,
      );
      appendHistory(
        documentNode, grid, "Recent starts", result.recent_launches || [],
        (row) => row.selected_surface || row.requested_surface,
      );
      appendAccess(documentNode, grid, context, result, load, status);
      appendRetirement(documentNode, grid, context, result, load, status);
      body.appendChild(grid);
    },
  );
  load();
}
