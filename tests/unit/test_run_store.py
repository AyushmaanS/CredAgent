import json
import subprocess
import sys
import textwrap

import pytest

from credagent.secrets.masking import Masker
from credagent.state import store as store_mod
from credagent.state.models import Handoff, Run, StepRecord
from credagent.state.store import RunNotFound, RunStore, SecretLeakError, StoreError


def make(tmp_path, masker=None):
    return RunStore(tmp_path / "runs", masker or Masker())


def test_create_checkpoint_load_roundtrip(tmp_path):
    s = make(tmp_path)
    r = s.create(Run(id="r1", app_input="Fakeprov"))
    r.add_step(StepRecord(action="navigate console", actor="agent", outcome="done"))
    s.checkpoint(r, "step", {"n": 1})
    loaded = s.load("r1")
    assert loaded.run.steps[0].action == "navigate console"
    assert loaded.in_doubt_action is None and loaded.events_after_snapshot == 0
    assert [e["type"] for e in s.events("r1")] == ["run_created", "step"]


def test_reload_in_fresh_process_after_handoff(tmp_path):
    s = make(tmp_path)
    r = s.create(Run(id="r2", app_input="Fakeprov"))
    r.open_handoff(Handoff(kind="DO", reason="Sign-in required", completed_so_far="1 of 6",
                           person_instruction="Sign in", where="browser",
                           expected_resume_action="re-check page"))
    s.checkpoint(r, "handoff_opened")
    code = textwrap.dedent(f"""
        import sys; sys.path.insert(0, {str(store_mod.__file__.rsplit('/credagent/', 1)[0])!r})
        from pathlib import Path
        from credagent.secrets.masking import Masker
        from credagent.state.store import RunStore
        r = RunStore(Path({str(tmp_path / 'runs')!r}), Masker()).load("r2").run
        print(r.pending_handoff.reason)
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "Sign-in required"


def test_crash_mid_action_is_reported_in_doubt(tmp_path):
    """A real process starts an action and dies before finishing it."""
    runs = tmp_path / "runs"
    code = textwrap.dedent(f"""
        import os, sys; sys.path.insert(0, {str(store_mod.__file__.rsplit('/credagent/', 1)[0])!r})
        from pathlib import Path
        from credagent.secrets.masking import Masker
        from credagent.state.models import Run
        from credagent.state.store import RunStore
        s = RunStore(Path({str(runs)!r}), Masker())
        r = s.create(Run(id="r3", app_input="Fakeprov"))
        s.begin_action(r, "click", {{"target": "Create app button"}})
        os._exit(9)  # killed before end_action
    """)
    p = subprocess.run([sys.executable, "-c", code])
    assert p.returncode == 9
    loaded = make(tmp_path).load("r3")
    assert loaded.in_doubt_action["action"] == "click"
    assert loaded.in_doubt_action["target"] == "Create app button"


def test_finished_action_not_in_doubt(tmp_path):
    s = make(tmp_path)
    r = s.create(Run(id="r4", app_input="x"))
    seq = s.begin_action(r, "fill", {"field": "name"})
    s.end_action(r, seq, "done")
    assert s.load("r4").in_doubt_action is None


def test_crash_between_event_and_snapshot(tmp_path, monkeypatch):
    s = make(tmp_path)
    r = s.create(Run(id="r5", app_input="x"))

    def boom(*a, **k):
        raise OSError("disk went away")

    monkeypatch.setattr(store_mod, "atomic_write_json", boom)
    with pytest.raises(OSError):
        s.begin_action(r, "click", {"target": "Create"})
    monkeypatch.undo()
    loaded = s.load("r5")
    assert loaded.events_after_snapshot == 1
    assert loaded.in_doubt_action["target"] == "Create"
    # new checkpoints continue the sequence without collisions
    s.checkpoint(loaded.run, "resumed")
    seqs = [e["seq"] for e in s.events("r5")]
    assert seqs == sorted(set(seqs))


def test_torn_event_tail_tolerated(tmp_path):
    s = make(tmp_path)
    s.create(Run(id="r6", app_input="x"))
    with open(tmp_path / "runs" / "r6" / "events.jsonl", "a") as f:
        f.write('{"seq": 2, "type": "acti')
    loaded = s.load("r6")
    assert loaded.torn_tail and loaded.run.id == "r6"


def test_leftover_tmp_file_ignored(tmp_path):
    s = make(tmp_path)
    s.create(Run(id="r7", app_input="x"))
    (tmp_path / "runs" / "r7" / ".run.json.999.tmp").write_text("{garbage")
    assert s.load("r7").run.id == "r7"


def test_corrupt_snapshot_is_plain_error(tmp_path):
    s = make(tmp_path)
    s.create(Run(id="r8", app_input="x"))
    (tmp_path / "runs" / "r8" / "run.json").write_text("{not json")
    with pytest.raises(StoreError, match="unreadable"):
        s.load("r8")


def test_registered_secret_never_written(tmp_path):
    secret = "Zr8-fake-shown-once-secret-Q2"  # fake; secret-scan: allow
    s = make(tmp_path, Masker([secret]))
    r = s.create(Run(id="r9", app_input="x"))
    r.add_step(StepRecord(action=f"saw {secret}", actor="agent", outcome="done"))
    with pytest.raises(SecretLeakError):
        s.checkpoint(r, "step")
    with pytest.raises(SecretLeakError):
        s.checkpoint(Run(id="r9", app_input="x"), "step", {"note": secret})
    on_disk = "".join(p.read_text() for p in (tmp_path / "runs" / "r9").iterdir())
    assert secret not in on_disk


def test_bad_ids_and_missing_runs(tmp_path):
    s = make(tmp_path)
    for bad in ["../x", "", ".hidden", "a/b"]:
        with pytest.raises(StoreError):
            s.load(bad)
    with pytest.raises(RunNotFound):
        s.load("nope")


def test_list_runs_and_owner_only_files(tmp_path):
    s = make(tmp_path)
    s.create(Run(id="a1", app_input="x"))
    s.create(Run(id="a2", app_input="y"))
    assert {r.id for r in s.list_runs()} == {"a1", "a2"}
    for p in (tmp_path / "runs" / "a1").iterdir():
        assert (p.stat().st_mode & 0o077) == 0
    assert json.loads((tmp_path / "runs" / "a1" / "run.json").read_text())["checkpoint_seq"] == 1
