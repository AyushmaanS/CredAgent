import { api } from "./api.js";
import { h, clear } from "./dom.js";
import { renderHeader } from "./components/header.js";
import { renderLanding } from "./components/landing.js";
import { renderConsent } from "./components/consent.js";
import { renderAttention } from "./components/attention.js";
import { renderProgressCard, renderRunHead, renderSteps } from "./components/progress.js";
import { renderResult } from "./components/result.js";
import { renderFailure, renderPaused } from "./components/failure.js";

const root = document.getElementById("app");
renderHeader(document.getElementById("header"));

// UI state. It holds no credential: secret values live only inside secret-field.js while revealed.
const S = {
  config: null, recent: [], runId: null, view: null, error: null, notice: null, busy: false, unauthorized: false,
  choice: null, focusKey: null, lastKey: "",
  draft: { app: "", mode: "real", scenario: "success", offline: true, account: "", advancedOpen: false },
  logState: { open: false, lines: [], after: 0 },
};
let pollTimer = null;

window.addEventListener("hashchange", route);
boot();

async function boot() {
  try { S.config = await api.config(); } catch (e) { fail(e); }
  route();
}

function fail(e) {
  if (e.status === 401) S.unauthorized = true;
  S.error = e.message;
}

async function route() {
  clearTimeout(pollTimer);
  const m = location.hash.match(/^#\/run\/([\w.-]+)/);
  const id = m ? decodeURIComponent(m[1]) : null;
  if (id !== S.runId) {
    S.view = null; S.choice = null; S.notice = null; S.focusKey = null;
    S.logState = { open: false, lines: [], after: 0 };
  }
  S.runId = id;
  S.error = S.unauthorized ? S.error : null;
  if (id) { render(true); poll(id); return; }
  try { S.recent = (await api.listRuns()).runs; } catch (e) { fail(e); }
  render(true);
}

async function poll(id) {
  if (S.runId !== id) return;
  try {
    S.view = await api.getRun(id);
    S.error = null;
  } catch (e) {
    S.view = e.status === 404 ? null : S.view;
    fail(e);
  }
  render();
  const settled = S.view && (S.view.state === "completed" || S.view.state === "failed");
  clearTimeout(pollTimer);
  pollTimer = setTimeout(() => poll(id), document.hidden ? 4000 : settled ? 5000 : 1000);
}

/** Run a UI action: show it is busy, report a failure in plain words, then refresh from the backend. */
async function act(fn) {
  S.busy = true; S.notice = null; render(true);
  try { await fn(); } catch (e) { S.notice = e.message; if (!S.runId) S.error = e.message; }
  S.busy = false;
  if (S.runId) await poll(S.runId); else render(true);
}

async function start() {
  const d = S.draft;
  await act(async () => {
    const body = d.mode === "fake" ? { app: d.app.trim(), mode: "fake", scenario: d.scenario || "success", offline: d.offline } : { app: d.app.trim() };
    const { run_id: id } = await api.startRun(body);
    S.error = null;
    location.hash = `#/run/${encodeURIComponent(id)}`;
  });
}

function home() { location.hash = "#/"; }

function render(force = false) {
  const key = JSON.stringify([S.view, S.error, S.notice, S.busy, S.choice, S.runId, S.draft.mode, S.recent, S.unauthorized]);
  if (!force && key === S.lastKey) return;
  S.lastKey = key;
  const active = document.activeElement;
  const keep = active && active.id && root.contains(active) ? { id: active.id, s: active.selectionStart, e: active.selectionEnd } : null;
  clear(root);
  root.append(build());
  if (keep) {
    const el = document.getElementById(keep.id);
    if (el) { el.focus(); try { el.setSelectionRange(keep.s, keep.e); } catch { /* not a text field */ } }
  }
  titleAndFocus();
}

function build() {
  if (S.unauthorized) {
    return h("section", { class: "card bad", role: "alert" }, h("h2", {}, "Open CredAgent from its link"),
      h("p", {}, "This page needs the one-time link that `credagent ui` prints in the terminal. Run it again, or open that link, to sign this browser in."));
  }
  if (!S.runId) {
    return renderLanding({ config: S.config, draft: S.draft, recent: S.recent, error: S.error, busy: S.busy,
      onStart: start, onOpenRun: () => {}, onChange: () => render(true) });
  }
  const v = S.view;
  if (!v) {
    return S.error
      ? h("section", { class: "card bad", role: "alert" }, h("h2", {}, "Can't show this run"), h("p", {}, S.error), h("div", { class: "actions" }, h("button", { class: "btn primary", type: "button", onclick: home }, "Back")))
      : h("p", { class: "spinner-line", role: "status" }, "Loading…");
  }
  const id = v.id;
  const logState = S.logState;
  const blocks = [renderRunHead(v)];
  if (S.error) blocks.push(h("div", { class: "error", role: "alert" }, S.error));
  switch (v.state) {
    case "attention": {
      const a = v.attention;
      blocks.push(a.type === "consent"
        ? renderConsent(a, { draft: S.draft, busy: S.busy, onConsent: () => act(async () => { await api.consent(id, S.draft.account); S.draft.account = ""; }), onStop: () => act(() => api.stop(id)) })
        : renderAttention(a, { busy: S.busy, choice: S.choice, canFocus: S.config && S.config.can_focus_browser, notice: S.notice,
          onFocusBrowser: () => act(async () => { const r = await api.focusBrowser(id); if (!r.ok) S.notice = "Couldn't raise the window from here. Switch to the Chrome window opened by CredAgent."; }),
          onDone: () => act(() => api.done(id, a.handoff_id)),
          onAnswer: () => act(async () => { await api.answer(id, a.handoff_id, S.choice); S.choice = null; }),
          onStop: () => act(() => api.stop(id)),
          onPick: (i) => { S.choice = i; render(true); } }));
      blocks.push(renderProgressCard(v, { logState }));
      break;
    }
    case "completed":
      blocks.push(renderResult(v, { busy: S.busy, notice: S.notice, onVerify: () => act(() => api.verify(id)), onNew: home }), renderSteps(v, { logState }));
      break;
    case "failed":
      blocks.push(renderFailure(v, { busy: S.busy, onResume: () => act(() => api.resume(id)), onRetry: () => retry(v), onHome: home }), renderSteps(v, { logState }));
      break;
    case "paused":
      blocks.push(renderPaused(v, { busy: S.busy, onResume: () => act(() => api.resume(id)), onHome: home }), renderProgressCard(v, { logState }));
      break;
    default:
      blocks.push(renderProgressCard(v, { logState }));
  }
  if (S.notice && v.state !== "attention" && v.state !== "completed") blocks.push(h("div", { class: "error", role: "alert" }, S.notice));
  return h("div", { class: "stack" }, blocks);
}

function retry(v) {
  S.draft.app = v.app.input; S.draft.mode = v.fake ? "fake" : "real";
  location.hash = "#/";
}

function titleAndFocus() {
  const v = S.view;
  const state = S.runId && v ? v.state : "idle";
  const name = v ? (v.app.name || v.app.input) : "";
  document.title = state === "attention" ? "● Your attention is needed · CredAgent" :
    state === "completed" ? `${name}: done · CredAgent` : state === "failed" ? `${name}: stopped · CredAgent` :
    state === "running" ? `${name}: working · CredAgent` : "CredAgent";
  // Move focus to the new panel's heading once, so assistive technology announces what changed.
  const key = v && S.runId ? `${S.runId}:${v.state}:${v.attention ? (v.attention.handoff_id || "consent") : ""}` : null;
  if (key && key !== S.focusKey && ["attention", "completed", "failed", "paused"].includes(v.state)) {
    S.focusKey = key;
    const hd = root.querySelector("h2[tabindex='-1']");
    if (hd) hd.focus({ preventScroll: false });
  } else if (!key) S.focusKey = null;
}
