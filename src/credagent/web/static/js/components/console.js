import { h } from "../dom.js";

/** Research could not find the console address: ask for it, instead of showing a plan that cannot start. */
export function renderConsolePrompt(attn, { draft, busy, notice, onSubmit, onStop }) {
  const field = h("input", { type: "text", id: "console-url", maxlength: "300", autocomplete: "off", spellcheck: "false",
    "aria-describedby": "console-help", placeholder: "https://console.example.com/apps", value: draft.consoleUrl || "",
    oninput: (e) => { draft.consoleUrl = e.target.value; go.disabled = busy || !draft.consoleUrl.trim(); } });
  const go = h("button", { class: "btn primary", type: "submit", disabled: busy || !(draft.consoleUrl || "").trim() }, "Continue");
  return h("section", { class: "card attention", "aria-labelledby": "attn-h" },
    h("div", { class: "attn-title" }, h("span", { class: "dot blocked", "aria-hidden": "true" }), attn.title),
    h("h2", { class: "big", id: "attn-h", tabindex: "-1" }, attn.headline),
    h("p", {}, attn.why),
    attn.allowed.length > 0 && h("p", { class: "fine" }, `Sites research found for this provider: ${attn.allowed.join(", ")}${attn.inferred.length ? ` (inferred from the app name: ${attn.inferred.join(", ")})` : ""}.`),
    h("form", { onsubmit: (e) => { e.preventDefault(); if (!go.disabled) onSubmit(); } },
      h("label", { class: "field", for: "console-url" }, h("span", { class: "muted" }, "Developer console address")),
      field,
      h("p", { class: "fine", id: "console-help" }, "It must start with https://. The address's site is allowed for this run only. Nothing happens at the provider until you give your go-ahead on the next screen."),
      notice && h("div", { class: "error", role: "alert" }, notice),
      h("div", { class: "actions" }, go, h("button", { class: "btn quiet", type: "button", disabled: busy, onclick: onStop }, "Not now"))));
}
