import { h, statusDot } from "../dom.js";

/** Failed or blocked runs, and paused ones: what happened, what was completed, what can be done next. */
export function renderFailure(view, { busy, onResume, onRetry, onHome }) {
  const f = view.failure;
  const tone = f.kind === "recoverable" || f.kind === "waiting" ? "blocked" : f.kind === "needs_you" ? "blocked" : "failed";
  return h("section", { class: `card ${tone === "failed" ? "bad" : "attention"}`, "aria-labelledby": "fail-h" },
    h("div", { class: "banner" }, statusDot(tone),
      h("div", {}, h("h2", { class: "big", id: "fail-h", tabindex: "-1" }, f.title),
        h("div", { class: "muted small" }, { recoverable: "Recoverable", needs_you: "Needs you", waiting: "Waiting", unrecoverable: "Not recoverable" }[f.kind]))),
    f.reason && h("p", {}, f.reason),
    f.blockers.length > 0 && h("ul", { class: "done-list" }, f.blockers.map((b) => h("li", {}, h("strong", {}, `${b.kind.replace(/_/g, " ")}: `), b.description))),
    f.completed.length > 0 && h("div", { class: "fine" }, h("strong", {}, "Completed before it stopped"),
      h("ul", { class: "done-list" }, f.completed.map((c) => h("li", {}, c)))),
    f.next_steps.length > 0 && h("div", { class: "todo" }, h("strong", {}, "What you can do"),
      h("ul", { class: "done-list" }, f.next_steps.map((s) => h("li", {}, s)))),
    h("div", { class: "actions" },
      f.can_resume && h("button", { class: "btn primary", type: "button", disabled: busy, onclick: onResume }, "Resume this run"),
      h("button", { class: f.can_resume ? "btn" : "btn primary", type: "button", disabled: busy, onclick: onRetry }, "Start again"),
      h("button", { class: "btn quiet", type: "button", onclick: onHome }, "Back")));
}

const PAUSED_TITLE = {
  terms_unchecked: "This provider's terms haven't been checked yet",
  terms_prohibited: "This provider's terms prohibit automation",
  config: "A key is missing",
};

export function renderPaused(view, { busy, onResume, onHome }) {
  const p = view.paused;
  return h("section", { class: "card attention", "aria-labelledby": "pause-h" },
    h("div", { class: "attn-title" }, h("span", { class: "dot blocked", "aria-hidden": "true" }), "Paused"),
    h("h2", { class: "big", id: "pause-h", tabindex: "-1" }, PAUSED_TITLE[p.error && p.error.kind] || "This run is saved and waiting"),
    p.error ? h("p", {}, p.error.message) : h("p", {}, "Nothing is running right now. The agent stops here when this page is closed or the app restarts; the run keeps its place."),
    p.done_so_far.length > 0 && h("div", { class: "fine" }, h("strong", {}, "Done so far"), h("ul", { class: "done-list" }, p.done_so_far.map((c) => h("li", {}, c)))),
    h("p", { class: "fine" }, "Resuming asks for your go-ahead again (for a real provider), re-opens or re-attaches to the browser window and re-checks the page. Nothing starts over."),
    h("div", { class: "actions" },
      p.can_resume && h("button", { class: "btn primary", type: "button", disabled: busy, onclick: onResume }, "Resume"),
      h("button", { class: "btn quiet", type: "button", onclick: onHome }, "Back")));
}
