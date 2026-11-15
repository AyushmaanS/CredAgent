#!/usr/bin/env python3
"""Sprint 0 spike: local state persistence + owner-only secret file on THIS machine,
at the real CREDAGENT_HOME (default ~/.credagent). Uses a fake value and deletes it.
Writes docs/spikes/storage.json.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from credagent.config.settings import REPO_ROOT, is_inside, load_settings  # noqa: E402
from credagent.secrets.store import SecretFileStore, ensure_private_dir  # noqa: E402
from credagent.state.atomic import append_jsonl, atomic_write_json  # noqa: E402

OUT = REPO / "docs" / "spikes" / "storage.json"


def mode(p: Path) -> str:
    return oct(stat.S_IMODE(p.stat().st_mode))


def tilde(text: str) -> str:
    """Committed spike output must not contain the owner's home path (it reveals the username)."""
    return text.replace(str(Path.home()), "~")


def main() -> int:
    s = load_settings()
    run_id = f"spike-{int(time.time())}"
    out: dict = {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "platform": platform.platform(),
                 "home": tilde(str(s.home)), "home_outside_repo": not is_inside(s.home, REPO_ROOT)}
    old = os.umask(0)
    os.umask(old)
    out["process_umask"] = oct(old)

    ensure_private_dir(s.home)
    store = SecretFileStore(s.secrets_dir)
    fake = "FAKE-" + secrets.token_urlsafe(24)
    ref = store.put(run_id, "client_secret", fake)
    f = s.secrets_dir / run_id / "client_secret.secret"
    out["secret_file"] = {"ref": ref, "file_mode": mode(f), "run_dir_mode": mode(f.parent),
                          "store_dir_mode": mode(s.secrets_dir), "home_mode": mode(s.home),
                          "owner_is_me": f.stat().st_uid == os.getuid()}
    code = ("import sys;sys.path.insert(0,%r);from credagent.secrets.store import SecretFileStore;"
            "from pathlib import Path;print(SecretFileStore(Path(%r)).get(%r)==%r)"
            % (str(REPO / "src"), str(s.secrets_dir), ref, fake))
    out["secret_readable_from_new_process"] = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True).stdout.strip() == "True"
    os.chmod(f, 0o644)
    try:
        store.get(ref)
        out["widened_mode_refused"] = False
    except Exception:
        out["widened_mode_refused"] = True
    shutil.rmtree(s.secrets_dir / run_id)
    out["fake_secret_removed"] = not (s.secrets_dir / run_id).exists()

    ckpt = s.runs_dir / run_id / "checkpoint.json"
    atomic_write_json(ckpt, {"run": run_id, "step": 2})
    append_jsonl(s.runs_dir / run_id / "events.jsonl", {"n": 1})
    code = f"import json;print(json.load(open({str(ckpt)!r}))['step'])"
    out["state"] = {
        "reload_in_new_process": subprocess.run([sys.executable, "-c", code], capture_output=True,
                                                text=True).stdout.strip() == "2",
        "checkpoint_mode": mode(ckpt), "run_dir_mode": mode(ckpt.parent),
        "runs_root_mode": mode(s.runs_dir), "profiles_root_mode": mode(ensure_private_dir(s.profiles_dir))}
    shutil.rmtree(s.runs_dir / run_id)

    tm = subprocess.run(["tmutil", "isexcluded", str(s.home)], capture_output=True, text=True)
    out["time_machine"] = tilde((tm.stdout or tm.stderr).strip()[:200])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
