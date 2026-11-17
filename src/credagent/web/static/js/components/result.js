import { h, statusDot, formatTime } from "../dom.js";
import { renderSecretField } from "./secret-field.js";

const PILL = { verified: "ok", client_recognized: "warn", inconclusive: "warn", untested: "warn", invalid: "bad" };
const PILL_TEXT = { verified: "Verified", client_recognized: "Partly verified", inconclusive: "Not verified", untested: "Not tested", invalid: "Rejected" };

/** The outcome: what was obtained, how it was checked, and the credentials (masked until revealed). */
export function renderResult(view, { busy, notice, onVerify, onNew }) {
  const r = view.result;
  const ok = r.verification.label === "verified" && !r.partial;
  return h("section", { class: `card ${ok ? "success" : ""}`, "aria-labelledby": "res-h" },
    h("div", { class: "banner" }, statusDot(ok ? "done" : "blocked"),
      h("div", {}, h("h2", { class: "big", id: "res-h", tabindex: "-1" }, view.headline),
        h("div", { class: "muted small" }, ok ? "The credential works: a live test with the provider passed." : "The credential was captured, but the live test did not fully pass."))),
    h("dl", { class: "kv" },
      h("dt", {}, "Application"), h("dd", {}, r.app, r.provider && h("span", { class: "muted" }, ` · ${r.provider}`)),
      h("dt", {}, "Authentication"), h("dd", {}, r.credential_type),
      h("dt", {}, "Verification"), h("dd", {}, h("span", { class: `pill ${PILL[r.verification.label] || "warn"}` }, PILL_TEXT[r.verification.label] || r.verification.label),
        h("div", { class: "small" }, r.verification.text),
        r.verification.observed && h("div", { class: "muted small" }, r.verification.observed)),
      r.verification.method && [h("dt", {}, "Method"), h("dd", {}, r.verification.method)],
      h("dt", {}, "Completed"), h("dd", {}, formatTime(r.completed_at)),
      r.permissions && [h("dt", {}, "Permissions"), h("dd", {}, r.permissions)]),
    r.verification.limitations.length > 0 && h("div", { class: "note" }, r.verification.limitations.join(" ")),
    h("div", { class: "creds", role: "group", "aria-label": "Credentials" }, r.parts.map((p) => renderSecretField(view.id, p))),
    h("p", { class: "fine" }, "Stored in owner-only files on this computer. Values stay masked until you press Reveal or Copy. They are never saved in this page."),
    r.created_items.length > 0 && h("p", { class: "fine" }, `Created at the provider: ${r.created_items.join("; ")}. ${r.cleanup}`),
    notice && h("p", { class: "fine", role: "status" }, notice),
    h("div", { class: "actions" },
      view.can_verify && h("button", { class: "btn", type: "button", disabled: busy, onclick: onVerify }, busy ? "Testing…" : "Run the live test again"),
      h("button", { class: "btn primary", type: "button", onclick: onNew }, "Get another")));
}
