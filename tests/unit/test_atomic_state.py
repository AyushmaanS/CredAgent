import json
import subprocess
import sys

from credagent.state.atomic import append_jsonl, atomic_write_json, read_json, read_jsonl


def test_atomic_roundtrip_in_fresh_process(tmp_path):
    path = tmp_path / "runs" / "r1" / "checkpoint.json"
    atomic_write_json(path, {"step": 3, "status": "running"})
    code = f"import json;print(json.load(open({str(path)!r}))['step'])"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "3"
    assert read_json(path)["status"] == "running"
    assert not list(path.parent.glob(".*.tmp"))


def test_overwrite_keeps_valid_json(tmp_path):
    path = tmp_path / "c.json"
    for i in range(20):
        atomic_write_json(path, {"i": i})
    assert read_json(path) == {"i": 19}


def test_jsonl_tolerates_torn_final_line(tmp_path):
    path = tmp_path / "events.jsonl"
    append_jsonl(path, {"n": 1})
    append_jsonl(path, {"n": 2})
    with open(path, "a") as f:
        f.write('{"n": 3, "trunc')
    assert [r["n"] for r in read_jsonl(path)] == [1, 2]


def test_files_are_owner_only(tmp_path):
    path = tmp_path / "c.json"
    atomic_write_json(path, {})
    assert (path.stat().st_mode & 0o077) == 0
    json.loads(path.read_text())
