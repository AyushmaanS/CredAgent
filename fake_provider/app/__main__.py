"""Run Fakeprov by hand: python -m fake_provider.app --scenario terms_checkbox [--port 8765]"""

from __future__ import annotations

import argparse
import time

from fake_provider.app import FakeProvider, load_scenarios, scenario
from fake_provider.app.server import TEST_EMAIL


def main() -> None:
    names = sorted(load_scenarios())
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", default="success", choices=names)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    with FakeProvider(scenario(args.scenario), port=args.port) as fp:
        print(f"Fakeprov ({args.scenario}) at {fp.base_url}  — test login: {TEST_EMAIL} "
              "(password in fake_provider/app/server.py). Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
