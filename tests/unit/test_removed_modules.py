"""D-078 phase 5 exit check: nothing imports the removed step machine, Jev, Stagehand or the legacy loop."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMOVED = re.compile(
    r"(?:from|import)\s+(?:stagehand\b|credagent\.(?:decisions|steps)\b|credagent\.browser\.(?:loop|session|candidates"
    r"|stagehand_llm)\b|credagent\.reasoning\.replan\b)")


def test_no_import_of_removed_modules():
    offenders = []
    for folder in ("src", "tests", "scripts", "fake_provider"):
        for f in (ROOT / folder).rglob("*.py"):
            if f.resolve() == Path(__file__).resolve():
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if REMOVED.search(line):
                    offenders.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_removed_packages_are_gone_and_not_a_dependency():
    for gone in ("decisions", "steps"):
        assert not (ROOT / "src" / "credagent" / gone).exists(), gone
    for gone in ("loop.py", "session.py", "candidates.py", "stagehand_llm.py"):
        assert not (ROOT / "src" / "credagent" / "browser" / gone).exists(), gone
    assert "stagehand" not in (ROOT / "pyproject.toml").read_text().lower()
