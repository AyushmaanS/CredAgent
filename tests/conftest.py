"""Global test isolation: no test may read the owner's real keys, touch ~/.credagent,
or reach the network through the real clients."""

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CREDAGENT_ENV_FILE", str(tmp_path / "no-env-file"))
    monkeypatch.setenv("CREDAGENT_HOME", str(tmp_path / "credagent-home"))
    monkeypatch.delenv("FASTROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
