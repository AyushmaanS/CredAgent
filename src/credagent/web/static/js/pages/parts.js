import { h } from "../dom.js";

// Small building blocks for the two reading pages. Built from plain elements and CSS classes only (no inline
// styles: the page's Content-Security-Policy forbids them), and every diagram has a text equivalent.

const WHO = { code: "Code", model: "Model", you: "You" };

/** A page: one h1 (focused on arrival), a lede, then sections. */
export function page(title, lede, ...blocks) {
  return h("div", { class: "doc" },
    h("h1", { tabindex: "-1" }, title),
    h("p", { class: "lede" }, lede),
    blocks);
}

export function section(title, intro, ...children) {
  return h("section", { class: "doc-section" },
    h("h2", { class: "doc-h2" }, title),
    intro && h("p", { class: "doc-intro" }, intro),
    children);
}

/** "Who acts" tag: colour plus the word, never colour alone. */
export function who(kind) {
  return h("span", { class: `who who-${kind}` }, WHO[kind]);
}

/** A vertical journey: numbered stages joined by a line, each with the actors that take part. */
export function journey(stages) {
  return h("ol", { class: "journey" }, stages.map((s, i) =>
    h("li", {},
      h("span", { class: "journey-n", "aria-hidden": "true" }, String(i + 1)),
      h("div", { class: "journey-body" },
        h("div", { class: "journey-head" }, h("strong", {}, s.title), h("span", { class: "who-row" }, s.who.map(who))),
        h("p", {}, s.text)))));
}

/** A cycle drawn as numbered cells with arrows, closed by a "back to 1" line. */
export function loop(cells, backText) {
  return h("div", { class: "loop" },
    h("ol", { class: "loop-grid" }, cells.map((c, i) =>
      h("li", { class: `loop-cell by-${c.by}` },
        h("span", { class: "loop-n", "aria-hidden": "true" }, String(i + 1)),
        h("strong", {}, c.title),
        h("span", { class: "loop-text" }, c.text),
        who(c.by)))),
    h("div", { class: "loop-back" }, h("span", { class: "loop-arrow", "aria-hidden": "true" }, "↩"), backText));
}

export function cards(items, cls = "") {
  return h("div", { class: `mini-cards ${cls}` }, items.map((c) =>
    h("div", { class: `mini ${c.tone ? `tone-${c.tone}` : ""}` },
      c.tag && h("div", { class: "mini-tag" }, c.tag),
      h("strong", {}, c.title),
      h("p", {}, c.text))));
}

export function list(items) {
  return h("ul", { class: "doc-list" }, items.map((t) => h("li", {}, t)));
}

export function callout(title, text) {
  return h("div", { class: "callout" }, h("strong", {}, title), h("span", {}, text));
}

export function stats(items) {
  return h("dl", { class: "stats" }, items.map((s) =>
    h("div", { class: "stat" }, h("dt", {}, s.label), h("dd", {}, s.value, s.note && h("span", { class: "stat-note" }, s.note)))));
}

export function cta(onHome) {
  return h("div", { class: "doc-cta" },
    h("button", { class: "btn primary", type: "button", onclick: onHome }, "Get credentials"),
    h("span", { class: "muted small" }, "Back to the home screen"));
}
