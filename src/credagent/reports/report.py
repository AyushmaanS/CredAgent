"""Run reports (PRD F10, spec §6.11): JSON + Markdown, and the terminal plan view.

Reports contain references and masked displays only. Every rendered string goes
through the Masker before it is returned or written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from credagent.secrets.masking import Masker
from credagent.state.atomic import atomic_write_json, mkdir_private
from credagent.state.models import Run

FACT_KINDS = ("sourced", "observed", "inferred", "unknown")


def next_steps(run: Run) -> list[str]:
    steps: list[str] = []
    for b in run.blockers:
        steps += [f"[{b.who_must_act}] {s}" for s in b.next_steps]
    h = run.pending_handoff
    if h:
        steps.append(f"[person] {h.person_instruction} Then run: credagent resume {run.id}")
    if run.status == "running" and run.phase == "planned" and not h:
        steps.append("[owner] Review the plan above. Browser execution is not available in this "
                     "version yet (Sprint 3); the run is saved and can be resumed then: "
                     f"credagent resume {run.id}")
    if run.status == "failed" and run.resumable:
        steps.append(f"[owner] When the failing service is reachable again, run: credagent resume {run.id}")
    if run.status == "partial" and run.verification:
        steps += [f"[owner] For production: {x}" for x in run.verification.production_limitations]
    return steps or ["Nothing further."]


def build_report(run: Run, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    p = run.plan
    cred = None
    if run.credential:
        cred = {"kind": run.credential.kind, "stored_outside_repo": True,
                "parts": {k: v.masked_display for k, v in run.credential.parts.items()}}
    research_actions = [e["data"] for e in (events or []) if e["type"] == "research_action"]
    return {
        "run_id": run.id, "app_input": run.app_input,
        "app": p.identification.canonical_name or run.app_name, "provider": p.identification.provider,
        "created_at": run.created_at, "updated_at": run.updated_at,
        "outcome": {"status": run.status, "phase": run.phase, "reason": run.status_reason,
                    "resumable": run.resumable},
        "predicted_outcome": p.predicted_outcome, "actual_outcome": run.actual_outcome,
        "credential": cred,
        "verification": (run.verification.model_dump() if run.verification
                         else {"label": "untested", "test_description": p.verification_procedure or None,
                               "observed_result": None, "production_limitations": []}),
        "plan": {"credential_kind": p.credential_kind, "console_url": p.console_url,
                 "allowed_domains": p.allowed_domains, "revision": p.revision,
                 "replans_used": run.replans_used,
                 "steps": [s.model_dump() for s in p.steps],
                 "expected_blockers": p.expected_blockers, "needs_redirect_uri": p.needs_redirect_uri,
                 "scopes": p.scopes, "dynamic_registration": p.dynamic_registration,
                 "metadata_url": p.metadata_url},
        "steps": {"by_actor": run.counts(),
                  "records": [s.model_dump() for s in run.steps]},
        "facts": {k: [f.model_dump() for f in p.facts if f.kind == k] for k in FACT_KINDS},
        "unknowns": p.unknowns,
        "validation_notes": p.validation_notes,
        "handoffs": [h.model_dump() for h in run.handoffs],
        "blockers": [b.model_dump() for b in run.blockers],
        "next_steps": next_steps(run),
        "untested": run.untested,
        "cleanup": ("Nothing was created at the provider (no browser actions were taken)."
                    if run.phase in ("created", "research", "planned") else
                    "See handoffs and steps for anything created at the provider."),
        "sources": [s.model_dump() for s in p.sources],
        "research_actions": research_actions,
    }


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


def render_markdown(r: dict[str, Any]) -> str:
    o, v = r["outcome"], r["verification"]
    lines = [
        f"# CredAgent report — {r['app'] or r['app_input']}",
        "",
        f"Run `{r['run_id']}` · provider: {r['provider'] or 'unknown'} · created {r['created_at']}",
        "",
        "## Outcome",
        f"- **Status:** {o['status']} (phase: {o['phase']}){' — ' + o['reason'] if o['reason'] else ''}",
        f"- **Predicted:** {r['predicted_outcome']} · **Actual:** {r['actual_outcome'] or 'not finished'}",
        f"- **Credential:** {r['credential']['kind'] if r['credential'] else 'not captured'}"
        + (" · " + ", ".join(f"{k}: {d}" for k, d in r["credential"]["parts"].items())
           if r["credential"] else ""),
        f"- **Verification:** `{v['label']}`"
        + (" — only `verified` counts as working" if v["label"] != "verified" else ""),
        "",
        "## What happened",
        f"- Agent actions: {r['steps']['by_actor']['agent']} · Person actions: "
        f"{r['steps']['by_actor']['person']} · System: {r['steps']['by_actor']['system']}",
    ]
    for s in r["steps"]["records"]:
        lines.append(f"- [{s['actor']}] {s['action']} → {s['outcome']}")
    lines += ["", "## Plan", f"- Credential type: {r['plan']['credential_kind']}",
              f"- Console: {r['plan']['console_url'] or 'unknown'}",
              f"- Allowed domains: {', '.join(r['plan']['allowed_domains']) or '(none)'}",
              f"- Redirect URI needed: {r['plan']['needs_redirect_uri']} · Dynamic registration: "
              f"{r['plan']['dynamic_registration']}", ""]
    lines += [f"{i}. {s['description']} `{s['kind']}`" for i, s in enumerate(r["plan"]["steps"], 1)]
    lines += ["", "## Facts"]
    for k in FACT_KINDS:
        items = [f["statement"] + (f" ([source]({f['source_url']}))" if f.get("source_url") else "")
                 for f in r["facts"][k]]
        lines += [f"**{k.capitalize()}**", _bullets(items), ""]
    lines += ["**Unknowns**", _bullets(r["unknowns"]), "",
              "## Corrections made by code to the model's plan", _bullets(r["validation_notes"]), "",
              "## Expected blockers", _bullets(r["plan"]["expected_blockers"]), "",
              "## Handoffs", _bullets([f"{h['kind']} ({h['status']}): {h['reason']}"
                                       + (f" → answer: {h['answer']}" if h.get("answer") else "")
                                       for h in r["handoffs"]]), "",
              "## Blockers", _bullets([f"{b['kind']}: {b['description']}" for b in r["blockers"]]), "",
              "## Verification", f"- Procedure: {v.get('test_description') or 'not defined'}",
              f"- Observed: {v.get('observed_result') or 'not run'}",
              "- Production limitations: " + (", ".join(v.get("production_limitations") or []) or "none recorded"),
              "", "## Next steps", _bullets(r["next_steps"]), "",
              "## Untested", _bullets(r["untested"]), "",
              "## Cleanup", f"- {r['cleanup']}", "",
              "## Sources", _bullets([f"[{s['title'] or s['url']}]({s['url']}) ({s['via']})"
                                      for s in r["sources"][:25]]), ""]
    return "\n".join(lines)


def write_reports(run: Run, run_dir: Path, masker: Masker,
                  events: list[dict[str, Any]] | None = None) -> tuple[Path, Path]:
    report = masker.mask(build_report(run, events))
    mkdir_private(run_dir)
    jpath, mpath = run_dir / "report.json", run_dir / "report.md"
    atomic_write_json(jpath, report)
    md = masker.mask_text(render_markdown(report))
    tmp = mpath.with_name(".report.md.tmp")
    tmp.write_text(md, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(mpath)
    return jpath, mpath


def render_plan(run: Run, masker: Masker | None = None) -> str:
    """Compact terminal view of the plan."""
    p = run.plan
    ident = p.identification
    out = [f"PLAN for {ident.canonical_name or run.app_input} ({ident.provider or 'provider unknown'}; "
           f"identification confidence: {ident.confidence})",
           f"  Credential: {p.credential_kind}   Predicted outcome: {p.predicted_outcome}",
           f"  Console: {p.console_url or 'unknown — will start from official docs'}",
           f"  Allowed domains: {', '.join(p.allowed_domains) or '(none)'}",
           f"  Redirect URI needed: {p.needs_redirect_uri}   Dynamic registration: {p.dynamic_registration}",
           "  Steps:"]
    out += [f"    {i}. [{s.kind}] {s.description}" for i, s in enumerate(p.steps, 1)]
    if p.expected_blockers:
        out.append("  Expected blockers:")
        out += [f"    - {b}" for b in p.expected_blockers]
    out.append(f"  Live test: {p.verification_procedure or 'not defined'}")
    counts = {k: sum(f.kind == k for f in p.facts) for k in FACT_KINDS}
    out.append("  Facts: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    if p.unknowns:
        out.append("  Unknowns:")
        out += [f"    - {u}" for u in p.unknowns[:8]]
    if p.validation_notes:
        out.append("  Corrected by code:")
        out += [f"    - {n}" for n in p.validation_notes[:8]]
    text = "\n".join(out)
    return (masker or Masker()).mask_text(text)


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)
