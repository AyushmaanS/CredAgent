#!/usr/bin/env python3
"""Secret scan for the CredAgent repository.

Modes:
  --staged   (default) files staged for commit, read from the git index
  --tree     every tracked file plus untracked files that are not ignored
  --history  every added line in all of git history

Checks:
  1. Forbidden paths (.env files other than .env.example, keys, secret files, runtime dirs).
  2. Exact values of the keys in .env.local (read in memory, never printed).
  3. Credential-shaped patterns (prefixed keys, private keys, JWTs, quoted random literals).

Findings print as `path:line: rule` only. Matched text is never printed.
A line containing `secret-scan: allow` is skipped (use only for obviously fake test data).
Exit code 1 if anything is found.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from credagent.config.settings import SECRET_KEYS, parse_env_file  # noqa: E402
from credagent.secrets.masking import PATTERNS, shannon_entropy  # noqa: E402

ALLOW_MARKER = "secret-scan: allow"
FORBIDDEN_PATH = re.compile(
    r"(^|/)\.env(\.(?!example$)[^/]*)?$"
    r"|\.(pem|key|secret|p12|pfx)$"
    r"|(^|/)\.credagent/|(^|/)(browser-data|chrome-user-data|secret-store)/"
)
_PATTERN_RULES = [(label, p) for label, p in PATTERNS if label in {"private_key", "jwt", "prefixed_key"}]
QUOTED_LITERAL = re.compile(
    r"(?i)(secret|api[_-]?key|token|password|passwd|client[_-]?secret)\w*[\"']?\s*[:=]\s*[\"']"
    r"([A-Za-z0-9_\-+/=.]{16,})[\"']"
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout


def known_values() -> list[tuple[str, str]]:
    env = parse_env_file(REPO / ".env.local")
    return [(k, v) for k, v in env.items() if k in SECRET_KEYS and len(v) >= 8]


def scan_text(path: str, text: str, known: list[tuple[str, str]]) -> list[str]:
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARKER in line:
            continue
        for name, value in known:
            if value in line:
                findings.append(f"{path}:{lineno}: value of {name} from .env.local")
        for label, pattern in _PATTERN_RULES:
            if pattern.search(line):
                findings.append(f"{path}:{lineno}: {label}")
        m = QUOTED_LITERAL.search(line)
        if m and shannon_entropy(m.group(2)) >= 3.5:
            findings.append(f"{path}:{lineno}: quoted secret-like literal")
    return findings


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8000]


def scan_files(paths: list[str], reader, known) -> list[str]:
    findings = []
    for p in paths:
        if FORBIDDEN_PATH.search(p):
            findings.append(f"{p}:0: forbidden file type/location (must never be committed)")
            continue
        data = reader(p)
        if data is None or is_binary(data):
            continue
        findings.extend(scan_text(p, data.decode("utf-8", errors="replace"), known))
    return findings


def staged(known) -> list[str]:
    paths = [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if p]

    def read(p: str) -> bytes | None:
        r = subprocess.run(["git", "show", f":{p}"], cwd=REPO, capture_output=True)
        return r.stdout if r.returncode == 0 else None

    return scan_files(paths, read, known)


def tree(known) -> list[str]:
    paths = [p for p in git("ls-files", "-co", "--exclude-standard").splitlines() if p]

    def read(p: str) -> bytes | None:
        f = REPO / p
        return f.read_bytes() if f.is_file() else None

    return scan_files(paths, read, known)


def history(known) -> list[str]:
    try:
        log = git("log", "-p", "--all", "--no-color", "--format=commit %H")
    except subprocess.CalledProcessError:
        return []  # no commits yet
    findings, commit, path = [], "", ""
    for line in log.splitlines():
        if line.startswith("commit "):
            commit = line.split()[1][:10]
        elif line.startswith("+++ b/"):
            path = line[6:]
            if FORBIDDEN_PATH.search(path):
                findings.append(f"{commit}:{path}: forbidden file type/location")
        elif line.startswith("+") and not line.startswith("+++"):
            for f in scan_text(path, line[1:], known):
                findings.append(f"{commit}:{f}")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true")
    g.add_argument("--tree", action="store_true")
    g.add_argument("--history", action="store_true")
    args = ap.parse_args()
    known = known_values()
    if args.tree:
        mode, findings = "working tree", tree(known)
    elif args.history:
        mode, findings = "git history", history(known)
    else:
        mode, findings = "staged files", staged(known)
    if findings:
        print(f"Secret scan FAILED ({mode}): {len(findings)} finding(s). Matched text is not shown.")
        for f in findings:
            print(f"  {f}")
        return 1
    print(f"Secret scan passed ({mode}; {len(known)} local key value(s) checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
