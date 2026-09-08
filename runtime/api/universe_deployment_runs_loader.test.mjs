import assert from "node:assert/strict";
import test from "node:test";

import {
  createDeploymentRunsLoader,
  RUNS_PAGE_SIZE,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_deployment_runs_loader.js";


function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function contextFor(client) {
  return { client, isMounted: () => true };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("initial load keeps all unfinished and appends completed pages", async () => {
  const requests = [];
  const replies = [
    ok({
      rows: [
        { id: "live", status: "executing" },
        { id: "done-1", status: "succeeded" },
      ],
      unfinished_count: 1,
      completed_match_count: 2,
      completed_loaded_count: 1,
      next_cursor: "cursor-1",
      filters: {
        projects: [{ id: 1, label: "yoke" }],
        statuses: ["executing", "succeeded"],
        environments: ["prod"],
        flows: [{ id: "release", label: "Release" }],
      },
    }),
    ok({
      rows: [
        { id: "live", status: "executing", current_stage: "verify" },
        { id: "done-2", status: "failed" },
      ],
      unfinished_count: 1,
      completed_match_count: 2,
      completed_loaded_count: 2,
      next_cursor: null,
      filters: null,
    }),
  ];
  const client = { async call(request) {
    requests.push(request);
    return replies.shift();
  } };
  const loader = createDeploymentRunsLoader({
    context: contextFor(client), scope: "all", onChange() {},
  });

  await loader.start();
  await loader.loadMore();

  assert.deepEqual(requests, [
    {
      function: "deployment_runs.list",
      payload: { page: { page_size: RUNS_PAGE_SIZE } },
    },
    {
      function: "deployment_runs.list",
      payload: { page: { page_size: RUNS_PAGE_SIZE, cursor: "cursor-1" } },
    },
  ]);
  assert.deepEqual(loader.state().rows.map((row) => row.id), [
    "live", "done-1", "done-2",
  ]);
  assert.equal(loader.state().unfinishedCount, 1);
  assert.equal(loader.state().completedMatchCount, 2);
  assert.equal(loader.state().completedLoadedCount, 2);
  assert.equal(loader.state().hasMore, false);
});

test("criteria reset paging and stale responses cannot overwrite them", async () => {
  const first = deferred();
  const second = deferred();
  const requests = [];
  const client = { call(request) {
    requests.push(request);
    return requests.length === 1 ? first.promise : second.promise;
  } };
  const loader = createDeploymentRunsLoader({
    context: contextFor(client), scope: ["1", "2"], onChange() {},
  });

  const oldRequest = loader.start();
  const newRequest = loader.setFilter("status", "failed");
  second.resolve(ok({
    rows: [{ id: "new", status: "failed" }],
    unfinished_count: 0,
    completed_match_count: 1,
    completed_loaded_count: 1,
    next_cursor: null,
    filters: {},
  }));
  await newRequest;
  first.resolve(ok({
    rows: [{ id: "stale", status: "executing" }],
    unfinished_count: 1,
    completed_match_count: 0,
    completed_loaded_count: 0,
    next_cursor: null,
    filters: {},
  }));
  await oldRequest;

  assert.deepEqual(requests[1].payload.page, {
    page_size: RUNS_PAGE_SIZE,
    projects: ["1", "2"],
    status: "failed",
  });
  assert.deepEqual(loader.state().rows.map((row) => row.id), ["new"]);
});

test("failed Load more retains rows and remains retryable", async () => {
  let calls = 0;
  const client = { async call() {
    calls += 1;
    if (calls === 1) return ok({
      rows: [{ id: "done-1", status: "succeeded" }],
      unfinished_count: 0,
      completed_match_count: 2,
      completed_loaded_count: 1,
      next_cursor: "cursor-1",
      filters: {},
    });
    return {
      status: 503,
      envelope: { success: false, error: { message: "temporarily unavailable" } },
    };
  } };
  const loader = createDeploymentRunsLoader({
    context: contextFor(client), scope: "all", onChange() {},
  });

  await loader.start();
  await loader.loadMore();

  assert.deepEqual(loader.state().rows.map((row) => row.id), ["done-1"]);
  assert.equal(loader.state().hasMore, true);
  assert.equal(loader.state().failure.status, 503);
});

test("project, environment, and flow changes reset the completed sequence", async () => {
  const requests = [];
  const client = { async call(request) {
    requests.push(request);
    return ok({
      rows: requests.length === 1 ? [{ id: "old", status: "succeeded" }] : [],
      unfinished_count: 0,
      completed_match_count: requests.length === 1 ? 2 : 0,
      completed_loaded_count: requests.length === 1 ? 1 : 0,
      next_cursor: requests.length === 1 ? "old-cursor" : null,
      filters: {},
    });
  } };
  const loader = createDeploymentRunsLoader({
    context: contextFor(client), scope: ["1", "2"], onChange() {},
  });

  await loader.start();
  await loader.setFilter("project", "2");
  await loader.setFilter("environment", "prod");
  await loader.setFilter("flow", "release");

  assert.deepEqual(requests.at(-1).payload.page, {
    page_size: RUNS_PAGE_SIZE,
    projects: ["2"],
    environment: "prod",
    flow: "release",
  });
  assert.deepEqual(loader.state().rows, []);
  assert.equal(loader.state().hasMore, false);
});

test("search is debounced into one newest-criteria request", async () => {
  const requests = [];
  const client = { async call(request) {
    requests.push(request);
    return ok({
      rows: [], unfinished_count: 0, completed_match_count: 0,
      completed_loaded_count: 0, next_cursor: null, filters: {},
    });
  } };
  const loader = createDeploymentRunsLoader({
    context: contextFor(client), scope: "all", onChange() {},
  });

  loader.setQuery("run");
  loader.setQuery("run-2026");
  await new Promise((resolve) => setTimeout(resolve, 300));

  assert.equal(requests.length, 1);
  assert.equal(requests[0].payload.page.search, "run-2026");
  loader.destroy();
});
