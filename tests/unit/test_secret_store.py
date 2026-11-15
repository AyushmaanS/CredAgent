import os
import stat

import pytest

from credagent.config.settings import REPO_ROOT
from credagent.secrets.store import SecretFileStore, SecretStoreError


def mode(p):
    return stat.S_IMODE(p.stat().st_mode)


def test_put_get_owner_only(tmp_path):
    store = SecretFileStore(tmp_path / "secrets")
    ref = store.put("run-1", "client_secret", "fake-value-123456")
    assert ref == "file:run-1/client_secret"
    assert store.get(ref) == "fake-value-123456"
    f = tmp_path / "secrets" / "run-1" / "client_secret.secret"
    assert mode(f) == 0o600
    assert mode(f.parent) == 0o700
    assert mode(tmp_path / "secrets") == 0o700


def test_widened_permissions_refused(tmp_path):
    store = SecretFileStore(tmp_path / "secrets")
    ref = store.put("run-1", "k", "fake-value-123456")
    os.chmod(tmp_path / "secrets" / "run-1" / "k.secret", 0o644)
    with pytest.raises(SecretStoreError):
        store.get(ref)


def test_store_inside_repo_refused():
    with pytest.raises(SecretStoreError):
        SecretFileStore(REPO_ROOT / "secret-store")


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "x" * 65])
def test_unsafe_identifiers_refused(tmp_path, bad):
    with pytest.raises(SecretStoreError):
        SecretFileStore(tmp_path).put(bad, "k", "fake-value-123456")


def test_nested_store_root_parents_owner_only(tmp_path):
    store = SecretFileStore(tmp_path / "home" / "secrets")
    store.put("run-1", "k", "fake-value-123456")
    assert mode(tmp_path / "home") == 0o700
