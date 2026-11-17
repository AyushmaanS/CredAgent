import { h } from "../dom.js";

// The two reading pages are reached from here; the landing page stays the home screen (the brand is its link).
const SECTIONS = [
  { hash: "#/how-it-works", label: "How it works" },
  { hash: "#/approach", label: "My approach" },
];

export function renderHeader(root) {
  const links = SECTIONS.map((s) => h("a", { class: "nav-link", href: s.hash }, s.label));
  const mark = () => {
    const here = location.hash;
    SECTIONS.forEach((s, i) => {
      if (here === s.hash) links[i].setAttribute("aria-current", "page");
      else links[i].removeAttribute("aria-current");
    });
  };
  window.addEventListener("hashchange", mark);
  mark();
  root.append(
    h("a", { class: "brand", href: "#/" }, h("img", { src: "/logo.svg", alt: "" }), "CredAgent"),
    h("nav", { class: "nav", "aria-label": "Sections" }, links));
}
