import { h } from "../dom.js";
import { api } from "../api.js";

const AUTO_HIDE_MS = 30_000;

/**
 * One credential value, masked by default. The value exists only inside this closure while it is revealed:
 * it is fetched on an explicit click, never stored (no localStorage, no sessionStorage, no module state), never
 * logged, hidden again after 30 seconds, when the tab is hidden, and when the element is removed.
 */
export function renderSecretField(runId, part) {
  let shown = null;
  let timer = null;
  let toast = null;
  const root = h("div", { class: "cred" });

  function hide() {
    shown = null;
    clearTimeout(timer);
    draw();
  }
  async function fetchValue() { return api.reveal(runId, part.name); }
  async function reveal() {
    try {
      shown = await fetchValue();
      toast = null;
      clearTimeout(timer);
      timer = setTimeout(hide, AUTO_HIDE_MS);
    } catch (e) { toast = { bad: true, text: e.message }; }
    draw();
  }
  async function copy() {
    let value = shown;
    try {
      if (value == null) value = await fetchValue();
      await writeClipboard(value);
      toast = { text: "Copied. Paste it where you need it, then copy something else over it." };
    } catch (e) { toast = { bad: true, text: e.message || "Could not copy." }; }
    value = null;
    draw();
    setTimeout(() => { toast = null; if (root.isConnected) draw(); }, 5000);
  }
  function draw() {
    root.replaceChildren(...[
      h("span", { class: "name" }, part.label),
      h("span", { class: "btns" },
        shown == null
          ? h("button", { class: "btn", type: "button", onclick: reveal, "aria-label": `Reveal ${part.label}` }, "Reveal")
          : h("button", { class: "btn", type: "button", onclick: hide, "aria-label": `Hide ${part.label}` }, "Hide"),
        h("button", { class: "btn", type: "button", onclick: copy, "aria-label": `Copy ${part.label}` }, "Copy")),
      h("span", { class: "val", "aria-live": "polite" }, shown == null ? part.masked : shown),
      toast && h("span", { class: toast.bad ? "error" : "toast", role: "status" }, toast.text)].filter(Boolean));
  }
  document.addEventListener("visibilitychange", () => { if (document.hidden) hide(); });
  draw();
  return root;
}

async function writeClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return; }
  const ta = document.createElement("textarea");  // fallback for http://127.0.0.1 in browsers that restrict the clipboard API
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.className = "skip";
  document.body.append(ta);
  ta.select();
  const ok = document.execCommand("copy");
  ta.remove();
  if (!ok) throw new Error("Could not copy. Reveal the value and copy it by hand.");
}
