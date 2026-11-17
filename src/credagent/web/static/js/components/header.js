import { h } from "../dom.js";

export function renderHeader(root) {
  const pop = h("div", { class: "info-pop", id: "info-pop", hidden: true, role: "dialog", "aria-label": "About CredAgent" },
    h("strong", {}, "How it works"),
    h("p", { class: "small" }, "CredAgent runs on this computer. It researches the app, works through the provider's developer console in a browser window you can see, and asks you whenever a step is yours: signing in, codes, CAPTCHAs, accepting terms."),
    h("p", { class: "small" }, "Credentials are stored in owner-only files on this machine and are masked here until you reveal them."));
  const btn = h("button", { class: "icon-btn", type: "button", "aria-label": "About CredAgent", "aria-expanded": "false", "aria-controls": "info-pop",
    onclick: () => {
      pop.hidden = !pop.hidden;
      btn.setAttribute("aria-expanded", String(!pop.hidden));
    } }, "i");
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { pop.hidden = true; btn.setAttribute("aria-expanded", "false"); btn.focus(); } });
  root.append(
    h("a", { class: "brand", href: "#/" }, h("img", { src: "/logo.svg", alt: "" }), "CredAgent"),
    h("div", { class: "info" }, btn, pop));
}
