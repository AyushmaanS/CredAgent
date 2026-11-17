import { h } from "../dom.js";

/** "Your attention is needed": what happened, what is done, exactly what to do, and the way to continue. */
export function renderAttention(attn, { busy, choice, canFocus, onFocusBrowser, onDone, onAnswer, onStop, onPick, notice }) {
  const isDecide = attn.type === "decide";
  const head = [
    h("div", { class: "attn-title" }, h("span", { class: "dot blocked", "aria-hidden": "true" }), attn.title),
    h("h2", { class: "big", id: "attn-h", tabindex: "-1" }, attn.headline),
    h("p", {}, attn.why),
  ];
  const doneSoFar = h("div", { class: "fine" }, h("strong", {}, "Done so far: "), attn.done_so_far,
    attn.done_milestones.length > 0 && h("ul", { class: "done-list" }, attn.done_milestones.map((m) => h("li", {}, m))));
  const todo = h("div", { class: "todo" }, h("strong", {}, isDecide ? "Your decision" : "What you need to do"),
    attn.instruction || (isDecide ? "Choose one option." : "Check the browser window and do what the page needs."),
    !isDecide && h("div", { class: "small muted" }, `Where: ${attn.where}. Afterwards the agent re-checks the page before it does anything else.`));
  let body;
  if (isDecide) {
    body = [todo, h("div", { class: "options", role: "radiogroup", "aria-label": "Options" },
      attn.options.map((o, i) => h("label", { class: "option" },
        h("input", { type: "radio", name: "choice", value: String(i), checked: choice === i, onchange: () => onPick(i) }), h("span", {}, o)))),
      h("div", { class: "actions" },
        h("button", { class: "btn primary", type: "button", disabled: busy || choice == null, onclick: onAnswer }, "Confirm choice"),
        h("button", { class: "btn quiet", type: "button", disabled: busy, onclick: onStop }, "Save and stop"))];
  } else {
    body = [todo, h("div", { class: "actions" },
      attn.can_focus_browser && canFocus && h("button", { class: "btn", type: "button", disabled: busy, onclick: onFocusBrowser }, "Open the browser window"),
      h("button", { class: "btn primary", type: "button", disabled: busy, onclick: onDone }, "I've done this"),
      h("button", { class: "btn quiet", type: "button", disabled: busy, onclick: onStop }, "Save and stop"))];
  }
  return h("section", { class: "card attention", "aria-labelledby": "attn-h" }, head, doneSoFar, body,
    notice && h("p", { class: "fine", role: "status" }, notice),
    h("p", { class: "fine" }, "“Save and stop” keeps the browser window and the run as they are. You can resume later and nothing starts over."));
}
