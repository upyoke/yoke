import assert from "node:assert/strict";
import test from "node:test";

import {
  endBlockerText,
  staleEligibilityText,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_diagnostics.js";
import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";


test("session card shows latest message, why active, and stale eligibility", () => {
  const documentNode = new FakeDocument();
  const createdAt = new Date(Date.now() - 4.2 * 60000).toISOString();
  const staleAt = new Date(Date.now() + 11.2 * 60000).toISOString();
  const row = {
    session_id: "session-1",
    liveness: "active",
    mode: "wait",
    executor: "codex",
    claims: [],
    coordination_leases: [],
    activity_at: createdAt,
    latest_message: {
      message_id: "message-1",
      state: "pending",
      created_at: createdAt,
    },
    end_blocker: {
      status: "chain_pending",
      checkpoint_step: 2,
      max_chain_steps: 3,
    },
    effective_stale_ttl_minutes: 60,
    stale_eligible_at: staleAt,
    messageability: { messageable: false },
  };
  const card = sessionCard(
    documentNode,
    row,
    { label: "member", value: () => "Ben" },
    "hosted",
    () => {},
  );

  const badge = byClass(card, "session-message-badge")[0];
  assert.equal(badge.textContent, "pending · 4m");
  assert.equal(
    byClass(card, "session-end-blocker")[0].textContent,
    "Why active: chain pending (step 2/3)",
  );
  assert.match(
    byClass(card, "session-stale-context")[0].textContent,
    /^Stale cleanup: stale-eligible in /,
  );
});


test("diagnostic text keeps blocker counts and terminal TTL behavior explicit", () => {
  assert.equal(
    endBlockerText({ status: "has_claims", active_claim_count: 1 }),
    "1 work claim held",
  );
  assert.equal(
    endBlockerText({
      status: "has_document_locks",
      active_document_lock_count: 2,
    }),
    "2 document locks held",
  );
  assert.equal(
    staleEligibilityText(
      { stale_eligible_at: "2026-08-22T12:12:00Z" },
      Date.parse("2026-08-22T12:00:00Z"),
    ),
    "stale-eligible in 12m",
  );

  const documentNode = new FakeDocument();
  const card = sessionCard(
    documentNode,
    {
      session_id: "terminated-1",
      liveness: "terminated",
      mode: "wait",
      executor: "codex",
      claims: [],
      coordination_leases: [],
      stale_eligible_at: "2099-01-01T00:00:00Z",
      messageability: { messageable: false },
    },
    { label: "member", value: () => "Ben" },
    "hosted",
    () => {},
  );
  assert.equal(byClass(card, "session-stale-context").length, 0);
});
