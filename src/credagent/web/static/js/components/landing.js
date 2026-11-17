import { h, formatTime } from "../dom.js";

const SUGGESTIONS = ["GitHub", "Linear", "Google Cloud"];
const STATE_TEXT = { completed: "Done", failed: "Stopped", paused: "Paused" };

export function renderLanding({ config, draft, recent, error, busy, onStart, onOpenRun, onChange }) {
  const keysMissing = config && !(config.keys.llm && config.keys.research);
  const test = draft.mode === "fake";
  const input = h("input", { type: "text", id: "app-name", name: "app", value: draft.app, maxlength: "100",
    placeholder: "Application name, for example GitHub", "aria-label": "Application name", autocomplete: "off", autocapitalize: "off", spellcheck: "false",
    oninput: (e) => { draft.app = e.target.value; refresh(); } });
  const submit = h("button", { class: "btn primary", type: "submit" }, "Get credentials");
  const blocked = () => !draft.app.trim() || busy || (!test && keysMissing);
  function refresh() { submit.disabled = blocked(); }
  refresh();

  const scenarioSel = h("select", { id: "scenario", "aria-label": "Test scenario", onchange: (e) => { draft.scenario = e.target.value; } },
    (config?.scenarios || []).map((s) => h("option", { value: s, selected: s === (draft.scenario || "success") }, s)));
  const advanced = h("details", { class: "adv", open: draft.advancedOpen, ontoggle: (e) => { draft.advancedOpen = e.target.open; } },
    h("summary", {}, "Advanced"),
    h("div", { class: "adv-body" },
      h("label", { class: "field" }, "Where to run",
        h("select", { id: "mode", onchange: (e) => { draft.mode = e.target.value; draft.advancedOpen = true; onChange(); } },
          h("option", { value: "real", selected: !test }, "A real application (research, then your browser)"),
          h("option", { value: "fake", selected: test }, "The local test site (no account needed)"))),
      test && h("label", { class: "field" }, "Test scenario", scenarioSel),
      test && h("label", { class: "check" },
        h("input", { type: "checkbox", id: "offline", checked: draft.offline, onchange: (e) => { draft.offline = e.target.checked; } }),
        "Use the offline stand-in (no model calls)")));

  return h("div", {},
    h("h1", {}, "Get access to any app."),
    h("p", { class: "lede" }, "Enter an application name. The agent works out how it issues credentials, gets them through the developer portal, asks you only when a step is yours, and checks that they work."),
    h("form", { onsubmit: (e) => { e.preventDefault(); if (!blocked()) onStart(); } },
      h("div", { class: "ask" }, input, submit),
      h("div", { class: "chips" }, h("span", { class: "muted small" }, "Try"),
        SUGGESTIONS.map((s) => h("button", { class: "chip", type: "button", onclick: () => { draft.app = s; input.value = s; refresh(); input.focus(); } }, s))),
      advanced),
    !test && keysMissing && h("div", { class: "note", role: "status" }, "To research a real application, add FASTROUTER_API_KEY and TAVILY_API_KEY to .env.local (see the README), then restart `credagent ui`. The local test site works without them in offline mode."),
    error && h("div", { class: "error", role: "alert" }, error),
    recent.length > 0 && h("section", { class: "recent", "aria-label": "Recent runs" },
      h("h2", {}, "Recent"),
      recent.slice(0, 5).map((r) => h("a", { href: `#/run/${encodeURIComponent(r.id)}`, onclick: () => onOpenRun(r.id) },
        h("span", {}, h("span", { class: "rname" }, r.app), r.fake && h("span", { class: "muted small" }, " · test site"),
          h("div", { class: "muted small" }, formatTime(r.updated_at))),
        h("span", { class: `badge ${r.state}` }, STATE_TEXT[r.state] || r.state)))));
}
