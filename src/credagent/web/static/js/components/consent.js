import { h } from "../dom.js";

/** The go-ahead for a real provider (ATTEMPT-PROTOCOL §2): everything the person must see, then their own words. */
export function renderConsent(attn, { draft, busy, onConsent, onStop }) {
  const t = attn.terms || {};
  const field = h("input", { type: "text", id: "account", maxlength: "120", autocomplete: "off", "aria-describedby": "account-help",
    placeholder: "for example: my dedicated test account", value: draft.account || "",
    oninput: (e) => { draft.account = e.target.value; go.disabled = busy || !draft.account.trim(); } });
  const go = h("button", { class: "btn primary", type: "submit", disabled: busy || !(draft.account || "").trim() }, `Run CredAgent against ${attn.provider}`);
  return h("section", { class: "card attention", "aria-labelledby": "attn-h" },
    h("div", { class: "attn-title" }, h("span", { class: "dot blocked", "aria-hidden": "true" }), attn.title),
    h("h2", { class: "big", id: "attn-h", tabindex: "-1" }, `Before the browser opens at ${attn.provider}`),
    h("p", { class: "muted" }, "Nothing has been done at the provider yet. This is what will happen if you go ahead."),
    h("dl", { class: "kv" },
      h("dt", {}, "Credential"), h("dd", {}, attn.credential),
      h("dt", {}, "Console"), h("dd", {}, attn.console, h("div", { class: "muted small" }, `Allowed sites: ${attn.domains.join(", ")}`),
        attn.domains_inferred && attn.domains_inferred.length > 0 && h("div", { class: "muted small" }, `Inferred from the app name, not named by research: ${attn.domains_inferred.join(", ")}. Check that they are right.`)),
      h("dt", {}, "Will create"), h("dd", {}, attn.will_create),
      attn.callback && [h("dt", {}, "Callback URL"), h("dd", {}, attn.callback)],
      h("dt", {}, "Permissions"), h("dd", {}, attn.permissions),
      h("dt", {}, "You do"), h("dd", {}, attn.you_do),
      h("dt", {}, "Predicted"), h("dd", {}, attn.predicted),
      h("dt", {}, "Live test"), h("dd", {}, attn.live_test),
      h("dt", {}, "Afterwards"), h("dd", {}, attn.afterwards),
      h("dt", {}, "Terms check"), h("dd", {}, t.finding === "unchecked" ? `Not checked. ${t.summary || ""}` : `${String(t.finding || "").replace("_", " ")} (${t.checked_on}). ${t.summary || ""}`)),
    t.unclear_note && h("div", { class: "note" }, t.unclear_note),
    attn.blockers.length > 0 && h("details", { class: "log" }, h("summary", {}, "Known blockers"),
      h("ul", { class: "done-list" }, attn.blockers.map((b) => h("li", {}, b)))),
    h("form", { onsubmit: (e) => { e.preventDefault(); if (!go.disabled) onConsent(); } },
      h("label", { class: "field", for: "account", style: undefined }, h("span", { class: "muted" }, `Which ${attn.provider} account will you sign in with?`)),
      field,
      h("p", { class: "fine", id: "account-help" }, "Describe it in your own words: no password and no email. Use your own account, preferably a dedicated test account. Your go-ahead is for this session only."),
      h("div", { class: "actions" }, go, h("button", { class: "btn quiet", type: "button", disabled: busy, onclick: onStop }, "Not now"))));
}
