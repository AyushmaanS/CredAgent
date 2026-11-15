"""Checkpoint store: one directory per run under ~/.credagent/runs/<run-id>/.

  run.json      latest full snapshot (atomic replace)
  events.jsonl  append-only history: every checkpoint, action intent and result

Write order per checkpoint: event line first (fsync), then the snapshot. So the
log is never behind the snapshot. On load, anything the log says happened after
the snapshot is surfaced instead of silently dropped.

Never-replay rule (spec §6.8): before a browser action the orchestrator calls
`begin_action`, and after it `end_action`. If a run is loaded and its last
action has no matching end, the action is reported as *in doubt*. Resume must
re-observe the page and reconcile, never repeat it blindly.

Secret guard: every write is checked against the Masker's registered values and
refused if any appears (SecretLeakError). That is always a bug upstream.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from credagent.secrets.masking import Masker
from credagent.state.atomic import append_jsonl, atomic_write_json, mkdir_private, read_jsonl
from credagent.state.models import Run, now

_ID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


class StoreError(Exception):
    pass


class SecretLeakError(StoreError):
    """A registered secret value was about to be written to run state or events."""


class RunNotFound(StoreError):
    pass


@dataclass(frozen=True)
class LoadedRun:
    run: Run
    in_doubt_action: dict[str, Any] | None   # last action_started with no action_finished
    events_after_snapshot: int               # events newer than run.json (crash between writes)
    torn_tail: bool                          # final event line was incomplete


class RunStore:
    def __init__(self, runs_dir: Path, masker: Masker) -> None:
        self.runs_dir = runs_dir
        self.masker = masker

    # ------------------------------------------------------------- paths

    def _dir(self, run_id: str) -> Path:
        if not run_id or not set(run_id) <= _ID_OK or len(run_id) > 64 or run_id.startswith("."):
            raise StoreError("invalid run id")
        return self.runs_dir / run_id

    def _guard(self, payload: str) -> None:
        if self.masker.contains_known(payload):
            raise SecretLeakError("refusing to write: run state contains a registered secret value")

    # ------------------------------------------------------------ writes

    def create(self, run: Run) -> Run:
        d = self._dir(run.id)
        if d.exists():
            raise StoreError(f"run {run.id} already exists")
        mkdir_private(d)
        self.checkpoint(run, "run_created", {"app_input": run.app_input})
        return run

    def _event(self, run: Run, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        run.checkpoint_seq += 1
        record = {"seq": run.checkpoint_seq, "at": now(), "type": type_, "data": data,
                  "status": run.status}
        line = json.dumps(record, sort_keys=True)
        self._guard(line)
        append_jsonl(self._dir(run.id) / "events.jsonl", record)
        return record

    def checkpoint(self, run: Run, event_type: str, data: dict[str, Any] | None = None) -> int:
        """Append an event and persist the full run snapshot. Returns the new seq."""
        snapshot = run.model_dump(mode="json")
        self._guard(json.dumps(snapshot))  # check before anything hits disk
        record = self._event(run, event_type, data or {})
        snapshot["checkpoint_seq"] = run.checkpoint_seq
        atomic_write_json(self._dir(run.id) / "run.json", snapshot)
        return record["seq"]

    def begin_action(self, run: Run, action: str, details: dict[str, Any] | None = None) -> int:
        """Record intent *before* touching the browser."""
        return self.checkpoint(run, "action_started", {"action": action, **(details or {})})

    def end_action(self, run: Run, started_seq: int, outcome: str,
                   details: dict[str, Any] | None = None) -> int:
        return self.checkpoint(run, "action_finished",
                               {"started_seq": started_seq, "outcome": outcome, **(details or {})})

    # ------------------------------------------------------------- reads

    def load(self, run_id: str) -> LoadedRun:
        d = self._dir(run_id)
        snap_path = d / "run.json"
        if not snap_path.exists():
            raise RunNotFound(f"no run with id {run_id}")
        try:
            run = Run.model_validate(json.loads(snap_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise StoreError(f"run {run_id} checkpoint is unreadable: {type(exc).__name__}") from None

        events_path = d / "events.jsonl"
        raw_lines = events_path.read_text(encoding="utf-8").splitlines() if events_path.exists() else []
        events = read_jsonl(events_path)
        torn = bool(raw_lines) and len([ln for ln in raw_lines if ln.strip()]) > len(events)

        newer = [e for e in events if e["seq"] > run.checkpoint_seq]
        finished = {e["data"].get("started_seq") for e in events if e["type"] == "action_finished"}
        started = [e for e in events if e["type"] == "action_started"]
        in_doubt = None
        if started and started[-1]["seq"] not in finished:
            last = started[-1]
            in_doubt = {"seq": last["seq"], "at": last["at"], **last["data"]}
        if newer:
            # Snapshot is behind the log: keep the seq monotonic so new events don't collide.
            run.checkpoint_seq = max(e["seq"] for e in events)
        return LoadedRun(run=run, in_doubt_action=in_doubt,
                         events_after_snapshot=len(newer), torn_tail=torn)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return read_jsonl(self._dir(run_id) / "events.jsonl")

    def list_runs(self) -> list[Run]:
        if not self.runs_dir.exists():
            return []
        runs = []
        for d in sorted(self.runs_dir.iterdir()):
            if d.is_dir() and (d / "run.json").exists():
                try:
                    runs.append(self.load(d.name).run)
                except StoreError:
                    continue
        return sorted(runs, key=lambda r: r.created_at, reverse=True)

    def delete(self, run_id: str) -> None:
        shutil.rmtree(self._dir(run_id))
