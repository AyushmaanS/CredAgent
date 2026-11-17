// Tiny DOM helpers. Everything is built with createElement and textContent: no innerHTML anywhere, so page
// content (which can include text from a provider's site) can never become markup.

const SVG = "http://www.w3.org/2000/svg";

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

function svg(paths, attrs = {}) {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("fill", "none");
  s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "3");
  s.setAttribute("stroke-linecap", "round");
  s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("aria-hidden", "true");
  for (const [k, v] of Object.entries(attrs)) s.setAttribute(k, v);
  for (const d of paths) {
    const p = document.createElementNS(SVG, "path");
    p.setAttribute("d", d);
    s.append(p);
  }
  return s;
}

const GLYPHS = {
  done: ["M5 12.5l4.5 4.5L19 7.5"],
  blocked: ["M12 7v6", "M12 17h.01"],
  failed: ["M7 7l10 10", "M17 7L7 17"],
};

const STATUS_TEXT = { done: "Completed", current: "In progress", pending: "Pending", blocked: "Needs attention", failed: "Failed" };

/** A status marker: colour is never the only signal (it has a text label for assistive technology). */
export function statusDot(status) {
  const dot = h("span", { class: `dot ${status}`, role: "img", "aria-label": STATUS_TEXT[status] || status });
  if (GLYPHS[status]) dot.append(svg(GLYPHS[status]));
  return dot;
}

export function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
