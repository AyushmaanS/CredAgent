import { h, statusDot } from "../dom.js";

/** The backend's real milestones, in order. Status comes from recorded facts; there is no percentage. */
export function renderTimeline(milestones) {
  return h("ol", { class: "timeline", "aria-label": "Progress" },
    milestones.map((m) => h("li", { class: m.status },
      statusDot(m.status),
      h("div", {}, h("div", { class: "label" }, m.label), m.detail && m.status !== "pending" && h("div", { class: "detail" }, m.detail)))));
}
