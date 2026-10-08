// Browser-side source for the card collections the wrapping-rows check
// renders. Each collection draws its real cards through the renderer the
// dashboard uses, filled with the widest content each card carries in
// practice, so a card grid's minimum is proven against what its cards hold.
export const SESSION_COLLECTIONS = new Set(["Sessions", "Work sessions"]);

export const cardSpecimenSource = (assets) => `
  import { sessionCard } from "${assets}universe_views_sessions.js";
  import { machineCard } from "${assets}universe_machines_panel.js";
  import { workItemCard, shippingRunCard } from "${assets}universe_work_cards.js";
  import { strategyDocumentCard } from "${assets}universe_strategy_cards.js";
  const minutesAgo = (count) => new Date(Date.now() - count * 60000).toISOString();
  // A steered worker carries the session card's widest rows at once:
  // identity, model facts, the steering scope chip, the latest-message badge.
  const steeredSession = (index) => ({
    session_id: "worker-" + index, liveness: "active", mode: "dash",
    turn_posture: "running", executor: "claude-code",
    executor_surface: "claude-desktop", executor_mark: "C",
    executor_class_name: "h-claude", execution_level: "DARIUS",
    actor_label: "Production deployment owner", model: "claude-opus-5-5",
    model_effort: "medium", usage_tokens: 9300000, usage_cost_usd: 3.33,
    claims: [], holdings: { current: [], previous: [], previous_remainder: 0 },
    messageability: { messageable: true, relay_connected: true },
    relay: "connected", machine_id: "machine-1",
    machine_name: "operator-workstation-sixteen-inch",
    current_item_title: "Upload the build cache after the deploy, not before it",
    latest_message: { created_at: minutesAgo(11), message_id: "message-" + index,
      state: "acknowledged" },
    steering_group_session_id: "seat",
    steering_group_scope: { project: "platform", project_id: 1,
      scope: { project_id: 1 }, strategy_docs: [] },
  });
  const project = { id: 1, slug: "platform", public_item_prefix: "DEMO" };
  const context = { document, projects: () => [project] };
  const builders = {
    "session-card": (index) => sessionCard(document, steeredSession(index), () => {},
      [project], new Map([["seat", "#7c3aed"]])),
    "machine-card": (index) => machineCard(document, {
      machine_id: "machine-" + index, hostname: "operator-workstation-sixteen-inch",
      owner: "Production deployment owner", liveness: "active", state: "silent",
      last_seen_at: minutesAgo(3),
    }, [steeredSession(index)], { openSessions: [steeredSession(index)],
      projectRows: [project], showManagement: true }),
    "work-item-card": (index) => workItemCard(document, {
      public_ref: "DEMO-" + (3700 + index), project_id: 1, project_sequence: 3700 + index,
      title: "Refuse a deployment dispatch whose bound commit is behind its dispatch ref",
      status: "implementing", workflow_id: "dash", created_at: minutesAgo(600),
    }, "all", { meta: "Waiting for DEMO-3801", timestamp: minutesAgo(540),
      timeLabel: "filed" }),
    "strategy-doc-card": (index) => strategyDocumentCard(document, {
      project_id: 1, slug: "SELF-HOSTED-WEB-" + index, state: "active",
      summary: "Tenant databases stay isolated while compute starts only when needed.",
      updated_at: minutesAgo(60),
    }, project),
    "shipping-run-card": (index) => shippingRunCard(context, {
      id: "run-20261007-0" + index, project: "platform", status: "executing",
      target_environment: "production", release_lineage: "launch.590",
      created_at: minutesAgo(30), started_at: minutesAgo(29), stages: [],
    }, "all", {}),
  };
  window.realCard = (cardClass, index) => builders[cardClass](index);
`;
