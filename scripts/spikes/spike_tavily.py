#!/usr/bin/env python3
"""Sprint 0 spike: Tavily search + extract. Needs TAVILY_API_KEY. Never prints the key.

Records latency, result counts and field shapes; stores titles/URLs only (page
content is untrusted and not committed).
Usage: .venv/bin/python scripts/spikes/spike_tavily.py
Writes docs/spikes/tavily.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from credagent.config.settings import load_settings  # noqa: E402
from credagent.research.tavily import TavilyClient, TavilyError  # noqa: E402
from credagent.secrets.masking import Masker  # noqa: E402

OUT = REPO / "docs" / "spikes" / "tavily.json"
QUERIES = [
    "GitHub create OAuth app client ID client secret developer settings",
    "Raindrop.io API developer app client credentials",  # less common app
    "zzqx nonexistent app developer API keys",  # nonsense input
]


def main() -> int:
    s = load_settings()
    if not s.tavily_api_key:
        print("TAVILY_API_KEY missing — see README 'Local environment'.")
        return 1
    masker = Masker()
    c = TavilyClient(s, masker)
    summary: dict = {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "searches": [], "extracts": []}
    first_urls: list[str] = []
    for q in QUERIES:
        try:
            r = c.search(q, max_results=5)
            results = r.get("results", [])
            summary["searches"].append({
                "query": q, "latency_ms": r["latency_ms"], "count": len(results),
                "result_fields": sorted(results[0].keys()) if results else [],
                "top": [{"title": x.get("title"), "url": x.get("url"), "score": x.get("score")}
                        for x in results[:5]],
            })
            if results and not first_urls:
                first_urls = [x["url"] for x in results[:2]]
        except TavilyError as exc:
            summary["searches"].append({"query": q, "error": str(exc)[:300]})
    if first_urls:
        try:
            r = c.extract(first_urls)
            summary["extracts"].append({
                "urls": first_urls, "latency_ms": r["latency_ms"],
                "ok": [{"url": x.get("url"), "chars": len(x.get("raw_content") or "")}
                       for x in r.get("results", [])],
                "failed": r.get("failed_results", []),
                "result_fields": sorted(r["results"][0].keys()) if r.get("results") else [],
            })
        except TavilyError as exc:
            summary["extracts"].append({"urls": first_urls, "error": str(exc)[:300]})
    text = masker.mask_text(json.dumps(summary, indent=2))
    assert s.tavily_api_key not in text
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
