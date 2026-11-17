import { h } from "../dom.js";

const SUGGESTIONS = ["GitHub", "Linear", "Google Cloud"];

/** The only thing on the landing page: one name, one button. Any application name is accepted. */
export function renderLanding({ config, draft, error, busy, onStart }) {
  const keysMissing = config && !(config.keys.llm && config.keys.research);
  const input = h("input", { type: "text", id: "app-name", name: "app", value: draft.app, maxlength: "100",
    placeholder: "Application name, for example GitHub", "aria-label": "Application name", autocomplete: "off", autocapitalize: "off", spellcheck: "false",
    oninput: (e) => { draft.app = e.target.value; refresh(); } });
  const submit = h("button", { class: "btn primary", type: "submit" }, "Get credentials");
  const blocked = () => !draft.app.trim() || busy || keysMissing;
  function refresh() { submit.disabled = blocked(); }
  refresh();

  return h("div", {},
    h("h1", {}, "Get access to any app."),
    h("p", { class: "lede" }, "Enter an application name. The agent works out how it issues credentials, gets them through the developer portal, asks you only when a step is yours, and checks that they work."),
    h("form", { onsubmit: (e) => { e.preventDefault(); if (!blocked()) onStart(); } },
      h("div", { class: "ask" }, input, submit),
      h("div", { class: "chips" }, h("span", { class: "muted small" }, "Try"),
        SUGGESTIONS.map((s) => h("button", { class: "chip", type: "button", onclick: () => { draft.app = s; input.value = s; refresh(); input.focus(); } }, s)))),
    keysMissing && h("div", { class: "note", role: "status" }, "To research an application, add FASTROUTER_API_KEY and TAVILY_API_KEY to .env.local (see the README), then restart `credagent ui`."),
    error && h("div", { class: "error", role: "alert" }, error));
}
