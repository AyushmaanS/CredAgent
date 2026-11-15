"""Owner-only secret file store outside the repository.

Layout: <secrets_dir>/<run_id>/<name>.secret  (dir 0700, file 0600).
Run state only ever holds the store reference string, never the value.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from credagent.config.settings import REPO_ROOT, is_inside

_SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class SecretStoreError(Exception):
    pass


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    if _mode(path) != 0o700:
        raise SecretStoreError(f"could not restrict {path} to owner-only (0700)")
    return path


class SecretFileStore:
    def __init__(self, root: Path) -> None:
        if is_inside(root, REPO_ROOT):
            raise SecretStoreError("secret store must be outside the repository")
        self.root = root

    def _path(self, run_id: str, name: str) -> Path:
        if not (_SAFE.match(run_id) and _SAFE.match(name)):
            raise SecretStoreError("run id and secret name must be simple identifiers")
        return self.root / run_id / f"{name}.secret"

    def put(self, run_id: str, name: str, value: str) -> str:
        """Write atomically with 0600 from creation; return a reference string."""
        ensure_private_dir(self.root)
        run_dir = ensure_private_dir(self.root / run_id)
        target = self._path(run_id, name)
        tmp = run_dir / f".{name}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, value.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, target)
        os.chmod(target, 0o600)
        self.check(run_id, name)
        return f"file:{run_id}/{name}"

    def get(self, ref: str) -> str:
        run_id, name = self._parse(ref)
        self.check(run_id, name)
        return self._path(run_id, name).read_text(encoding="utf-8")

    def exists(self, ref: str) -> bool:
        run_id, name = self._parse(ref)
        return self._path(run_id, name).exists()

    def check(self, run_id: str, name: str) -> None:
        """Refuse to use a secret file whose permissions are wider than owner-only."""
        path = self._path(run_id, name)
        for p, want in ((self.root, 0o700), (path.parent, 0o700), (path, 0o600)):
            if _mode(p) != want:
                raise SecretStoreError(
                    f"{p} has permissions {oct(_mode(p))}, expected {oct(want)}"
                )
            if p.stat().st_uid != os.getuid():
                raise SecretStoreError(f"{p} is not owned by the current user")

    @staticmethod
    def _parse(ref: str) -> tuple[str, str]:
        if not ref.startswith("file:") or ref.count("/") != 1:
            raise SecretStoreError("unrecognised secret reference")
        run_id, name = ref[len("file:"):].split("/")
        return run_id, name
