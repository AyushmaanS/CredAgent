// The only module that talks to the backend. Components never call fetch.

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { "X-CredAgent": "1", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "offline", "Can't reach CredAgent. Is `credagent ui` still running?");
  }
  let data = null;
  try { data = await res.json(); } catch { /* an empty or non-JSON body */ }
  if (!res.ok) {
    const e = (data && data.error) || {};
    throw new ApiError(res.status, e.code || "error", e.message || `Request failed (${res.status}).`);
  }
  return data;
}

const run = (id) => `/api/runs/${encodeURIComponent(id)}`;

export const api = {
  config: () => request("GET", "/api/config"),
  startRun: (payload) => request("POST", "/api/runs", payload),
  getRun: (id) => request("GET", run(id)),
  events: (id, after) => request("GET", `${run(id)}/events?after=${after}`),
  consent: (id, account) => request("POST", `${run(id)}/consent`, { account, confirm: true }),
  answer: (id, handoffId, option) => request("POST", `${run(id)}/answer`, { handoff_id: handoffId, option }),
  done: (id, handoffId) => request("POST", `${run(id)}/continue`, { handoff_id: handoffId }),
  stop: (id) => request("POST", `${run(id)}/stop`, {}),
  resume: (id) => request("POST", `${run(id)}/resume`, {}),
  verify: (id) => request("POST", `${run(id)}/verify`, {}),
  focusBrowser: (id) => request("POST", `${run(id)}/browser/focus`, {}),
  // One stored value, on an explicit click. The caller must keep it in memory only and never log or store it.
  reveal: async (id, part) => (await request("POST", `${run(id)}/secrets/${encodeURIComponent(part)}/reveal`, { confirm: true })).value,
};
