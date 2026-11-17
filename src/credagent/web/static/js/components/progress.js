import { h } from "../dom.js";
import { renderTimeline } from "./timeline.js";
import { renderActivityLog } from "./activity-log.js";

const SUBTITLE = { running: "Working on it", attention: "Your attention is needed", paused: "Paused", completed: "Finished", failed: "Stopped" };

/** The application name and a one-line status. */
export function renderRunHead(view) {
  const name = view.app.name || view.app.input;
  return h("div", {},
    h("div", { class: "run-head" }, h("h1", {}, name), view.fake && h("span", { class: "badge" }, "local test site")),
    h("p", { class: "status-line" },
      view.state === "running" && h("span", { class: "dot current", role: "img", "aria-label": "In progress" }),
      SUBTITLE[view.state] || view.state,
      view.app.provider && view.app.provider !== name && h("span", { class: "muted small" }, `· ${view.app.provider}`)));
}

/** Milestones from the backend, the latest meaningful activity, and the collapsed technical log. */
export function renderProgressCard(view, { logState }) {
  return h("section", { class: "card", "aria-label": "Workflow progress" },
    renderTimeline(view.milestones),
    view.activity && h("div", { class: "activity", "aria-live": "polite" }, h("span", { class: "lab" }, "Latest"), h("span", { class: "txt" }, view.activity.text)),
    renderActivityLog(view.id, logState));
}

/** The same milestones, collapsed, for finished runs. */
export function renderSteps(view, { logState }) {
  return h("details", { class: "log" }, h("summary", {}, "Steps taken"), renderTimeline(view.milestones), renderActivityLog(view.id, logState));
}
