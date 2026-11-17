import { h, clear } from "../dom.js";
import { api } from "../api.js";

/** Technical events, collapsed by default; loaded only when opened. Text comes from the backend's masked events. */
export function renderActivityLog(runId, state) {
  const pre = h("pre", { "aria-label": "Technical activity log" });
  const details = h("details", { class: "log", open: state.open, ontoggle: (e) => { state.open = e.target.open; if (state.open) load(); } },
    h("summary", {}, "Activity log"), pre);
  let timer = null;
  async function load() {
    if (!state.open) return;
    try {
      const { events } = await api.events(runId, state.after || 0);
      if (events.length) {
        state.after = events[events.length - 1].seq;
        state.lines = (state.lines || []).concat(events.map((e) => `${String(e.seq).padStart(3, " ")}  ${(e.at || "").slice(11, 19)}  ${e.type}  ${e.text}`)).slice(-300);
      }
      clear(pre).append(document.createTextNode((state.lines || []).join("\n") || "No events yet."));
    } catch { /* the main poll shows connection problems */ }
    clearTimeout(timer);
    if (details.isConnected && state.open) timer = setTimeout(load, 2000);
  }
  if (state.open) { pre.textContent = (state.lines || []).join("\n") || "Loading…"; load(); }
  return details;
}
