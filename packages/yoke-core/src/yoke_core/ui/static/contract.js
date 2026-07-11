// Runtime half of the universe-app mount contract. Keep this module free of
// DOM assumptions so a host can import the contract version and construct a
// client before it chooses a mount root.

export { UNIVERSE_APP_CONTRACT_VERSION } from "./contract-version.js";

const DEFAULT_CALL_ENDPOINT = "/api/functions/call";

// The default same-origin client. Other shells inject their own client into
// mountUniverseApp so routing and authentication stay at the host boundary.
export function createHttpFunctionClient(options = {}) {
  const endpoint = options.endpoint || DEFAULT_CALL_ENDPOINT;
  const fetchImpl = options.fetch || globalThis.fetch;
  if (typeof fetchImpl !== "function") {
    throw new TypeError("createHttpFunctionClient requires a fetch function");
  }

  return {
    async call(request) {
      const response = await fetchImpl(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      // Read text first: an error body may not be JSON (proxy/server failure
      // pages), and an unconditional response.json() would strand the panel.
      const text = await response.text();
      let envelope;
      try {
        envelope = JSON.parse(text);
      } catch (parseError) {
        envelope = {
          success: false,
          error: {
            message: text.trim().slice(0, 200) || "empty non-JSON response",
          },
        };
      }
      return { status: response.status, envelope };
    },
  };
}
