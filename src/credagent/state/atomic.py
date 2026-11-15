"""Crash-safe JSON persistence primitives used by the checkpoint store."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def mkdir_private(path: Path) -> Path:
    """Create `path` and any missing parents, each owner-only (0700).

    `Path.mkdir(parents=True, mode=...)` applies `mode` only to the last component,
    so intermediate directories would otherwise get the default 0755.
    """
    missing = []
    p = path
    while not p.exists():
        missing.append(p)
        p = p.parent
    for d in reversed(missing):
        d.mkdir(mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    return path


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON so a reader sees either the old file or the new one, never a partial."""
    mkdir_private(path.parent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append one event line and fsync. A torn final line is tolerated by read_jsonl."""
    mkdir_private(path.parent)
    line = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break  # torn final write from a crash; ignore it
            raise
    return records
