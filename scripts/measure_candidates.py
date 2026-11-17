"""Measure how many page elements Jev should see (design docs/design/checkable-steps.md §11a).

Fake provider only: no real provider is contacted. For crowded pages that copy Discord's layout (and a few
ordinary pages), each case has one known correct element. The candidate list is built exactly as the agent
builds it (plain-code observation → dom_candidates → rank_for_goal → normalise), in variants:

  limit:  20 / 40 / 60
  order:  ranked | target_first | target_last (target placed at the last position still inside the limit)

Each variant is sent to Jev `--repeats` times. Only metrics are recorded (no page text):
correct element, "none" while the target was offered, confidence, latency, request size, served version.

    .venv/bin/python scripts/measure_candidates.py --offline --repeats 1   # dry run with the rule-based stand-in
    .venv/bin/python scripts/measure_candidates.py --repeats 3              # real Jev via FastRouter
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fake_provider.app import FakeProvider, Scenario  # noqa: E402

import credagent.browser.candidates as cmod  # noqa: E402
from credagent.browser.candidates import FieldValues, dom_candidates, normalise  # noqa: E402
from credagent.browser.loop import rank_for_goal  # noqa: E402
from credagent.browser.observe import observe_page  # noqa: E402
from credagent.browser.session import open_session  # noqa: E402
from credagent.decisions.client import DecisionLog, JevClient, RuleJev  # noqa: E402
from credagent.decisions.jev import NONE_OPTION, PageState, build_questions  # noqa: E402
from credagent.secrets.masking import Masker  # noqa: E402

CB = "http://127.0.0.1:8976/callback"
LIMITS = (20, 40, 60)
ORDERS = ("ranked", "target_first", "target_last")
OUT_JSON = ROOT / "docs" / "samples" / "candidate-limit.json"
OUT_MD = ROOT / "docs" / "samples" / "candidate-limit.md"
OTHER_APPS = [
    "o-t-2 oauthpath-test-20261029",
    "music-bot",
    "staging-integration",
    "analytics-dashboard",
    "test-client-7",
]


def cases(app_id: str, app_name: str) -> list[dict]:
    """(page, step goal, predicate for the one correct element). Some goals quote the target, some do not."""
    mine = f"{app_name}"
    return [
        {
            "page": "app",
            "path": f"/apps/{app_id}",
            "goal": "In the left sidebar of the application, open the OAuth2 page.",
            "target": lambda d: d == "link 'OAuth2'",
        },
        {
            "page": "app",
            "path": f"/apps/{app_id}",
            "goal": "Go to the page with the client credentials and redirects.",
            "target": lambda d: d == "link 'OAuth2'",
        },
        {
            "page": "oauth2",
            "path": f"/apps/{app_id}/oauth2",
            "goal": "Under Redirects, click 'Add Redirect', enter the exact callback URL, and save changes.",
            "target": lambda d: d == "button 'Add Redirect'",
        },
        {
            "page": "oauth2",
            "path": f"/apps/{app_id}/oauth2",
            "goal": "On the OAuth2 page, click 'Reset Secret' to generate a new client secret.",
            "target": lambda d: d == "button 'Reset Secret'",
        },
        {
            "page": "oauth2",
            "path": f"/apps/{app_id}/oauth2",
            "goal": "Generate a new client secret.",
            "target": lambda d: d == "button 'Reset Secret'",
        },
        {
            "page": "list",
            "path": "/console",
            "goal": "Open the application you just created from the list.",
            "target": lambda d: mine in d,
        },
        {
            "page": "list",
            "path": "/console",
            "goal": f"Click the '{app_name}' application to open it.",
            "target": lambda d: mine in d,
        },
        {
            "page": "form",
            "path": "/apps/new",
            "goal": "Fill in the application name field.",
            "target": lambda d: d.startswith("text field 'Application name'"),
        },
        {
            "page": "home",
            "path": "/",
            "goal": "Open the developer console.",
            "target": lambda d: d == "link 'Go to the developer console'" or d == "link 'Console'",
        },
    ]


def arrange(ranked: list, target_idx: int, limit: int, order: str) -> list:
    items = list(ranked)
    t = items.pop(target_idx)
    if order == "ranked":
        items.insert(target_idx, t)
    elif order == "target_first":
        items.insert(0, t)
    else:  # target_last: the last position that is still offered
        items.insert(min(limit, len(items) + 1) - 1, t)
    return items


async def observe_all(fp: FakeProvider, case_list: list[dict], masker: Masker) -> dict[str, object]:
    out: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as tmp:
        sess = await open_session(Path(tmp) / "profile", headless=True)
        try:
            for path in sorted({c["path"] for c in case_list}):
                await sess.page.goto(fp.base_url + path)
                await sess.page.wait_for_timeout(500)
                out[path] = await observe_page(sess.page, masker)
        finally:
            await sess.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="rule-based stand-in instead of Jev (dry run)")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    masker = Masker()
    if args.offline:
        jev = RuleJev()
    else:
        from credagent.config.settings import load_settings
        from credagent.reasoning.fastrouter import FastRouterClient

        s = load_settings()
        for k in (s.fastrouter_api_key, s.tavily_api_key):
            if k:
                masker.register(k, "api_key")
        jev = JevClient(FastRouterClient(s, masker))

    sc = Scenario(
        require_signin=False,
        terms="none",
        cookie_banner="none",
        numeric_client_id=True,
        secret_after_reset=True,
        crowded_oauth2=True,
    )
    app_name = FieldValues.default(CB).app_name
    rows: list[dict] = []
    with FakeProvider(sc) as fp:
        for n in OTHER_APPS:
            fp.state._new_app(n, CB)
        app = fp.state._new_app(app_name, CB)
        case_list = cases(app.id, app_name)
        pages = asyncio.run(observe_all(fp, case_list, masker))
        for ci, case in enumerate(case_list):
            obs = pages[case["path"]]
            dom = [
                replace(r, description=r.description + " (the app this run created)")
                if r.method == "click" and app_name in r.description
                else r
                for r in dom_candidates(obs)
            ]
            ranked = rank_for_goal(dom, case["goal"])
            tidx = next((i for i, r in enumerate(ranked) if case["target"](r.description)), None)
            if tidx is None:
                print(f"case {ci}: target not on the page; skipped", file=sys.stderr)
                continue
            for limit in LIMITS:
                for order in ORDERS:
                    arranged = arrange(ranked, tidx, limit, order)
                    cmod.MAX_CANDIDATES = limit
                    cands, mapping = normalise(arranged)
                    target_id = next((cid for cid, r in mapping.items() if case["target"](r.description)), None)
                    state = PageState(
                        step_goal=case["goal"],
                        url=obs.url_masked,
                        title=obs.title,
                        visible_text=obs.text[:6000],
                        candidates=cands,
                    )
                    req_chars = len(json.dumps(state.model_dump())) + len(json.dumps(build_questions(state)))
                    for rep in range(args.repeats):
                        log = DecisionLog()
                        t0 = time.monotonic()
                        d = jev.decide(state, log)
                        ms = round((time.monotonic() - t0) * 1000)
                        el = d["element_selection"]
                        rows.append(
                            {
                                "case": ci,
                                "page": case["page"],
                                "quoted": "'" in case["goal"],
                                "limit": limit,
                                "order": order,
                                "rep": rep,
                                "offered": len(cands),
                                "page_candidates": len(dom),
                                "target_rank": tidx,
                                "target_in_list": target_id is not None,
                                "chosen": el.value,
                                "correct": el.value == target_id and target_id is not None,
                                "said_none": el.value in (None, NONE_OPTION),
                                "uncertain": el.uncertain,
                                "confidence": el.confidence,
                                "latency_ms": ms,
                                "request_chars": req_chars,
                                "jev_failed": log.jev_failed,
                                "served_model": d.model,
                            }
                        )
                    print(
                        f"case {ci} limit {limit} {order}: "
                        f"{sum(r['correct'] for r in rows[-args.repeats :])}/{args.repeats} correct",
                        file=sys.stderr,
                    )
    cmod.MAX_CANDIDATES = 20
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "offline": args.offline,
        "repeats": args.repeats,
        "date": time.strftime("%Y-%m-%d"),
        "served_models": sorted({r["served_model"] or "?" for r in rows}),
    }
    OUT_JSON.write_text(json.dumps({"meta": meta, "rows": rows}, indent=1), encoding="utf-8")
    OUT_MD.write_text(summary(rows, meta), encoding="utf-8")
    print(OUT_MD.read_text(encoding="utf-8"))


def summary(rows: list[dict], meta: dict) -> str:
    lines = [
        "# Candidate-limit measurement (design §11a)",
        "",
        f"Date {meta['date']} · {'OFFLINE dry run (rule-based stand-in, not Jev)' if meta['offline'] else 'real Jev'}"
        f" · repeats {meta['repeats']} · served: {', '.join(meta['served_models'])}",
        "",
        "| limit | order | calls | target offered | correct (when offered) | said none (when offered) | "
        "median ms | p90 ms | mean request chars |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for limit in LIMITS:
        for order in ORDERS:
            rs = [r for r in rows if r["limit"] == limit and r["order"] == order]
            if not rs:
                continue
            off = [r for r in rs if r["target_in_list"]]
            lat = sorted(r["latency_ms"] for r in rs)
            p90 = lat[min(len(lat) - 1, int(round(0.9 * (len(lat) - 1))))]
            pct = lambda xs, n: f"{100 * sum(xs) / n:.0f} %" if n else "–"  # noqa: E731
            lines.append(
                f"| {limit} | {order} | {len(rs)} | {pct([1] * len(off), len(rs))} | "
                f"{pct([r['correct'] for r in off], len(off))} | {pct([r['said_none'] for r in off], len(off))} | "
                f"{statistics.median(lat):.0f} | {p90} | {statistics.mean(r['request_chars'] for r in rs):.0f} |"
            )
    lines += ["", "Per page (ranked order): target rank on the page and candidates on the page", ""]
    seen = set()
    for r in rows:
        if r["order"] == "ranked" and r["limit"] == 20 and (r["case"]) not in seen:
            seen.add(r["case"])
            lines.append(
                f"- case {r['case']} ({r['page']}, {'quoted' if r['quoted'] else 'not quoted'}): "
                f"target ranked #{r['target_rank'] + 1} of {r['page_candidates']} page candidates"
            )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
