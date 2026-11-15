import pytest

from credagent.config.settings import REPO_ROOT, ConfigError, load_settings, parse_env_file


def test_parse_env_file(tmp_path):
    f = tmp_path / ".env.local"
    f.write_text("# c\nA=1\nB='two'\nC=\"three\"\nnot a line\nD=\n")
    assert parse_env_file(f) == {"A": "1", "B": "two", "C": "three", "D": ""}


def test_defaults_and_repr_hides_keys(tmp_path):
    f = tmp_path / ".env.local"
    f.write_text("FASTROUTER_API_KEY=fake-key-for-test-123\n")
    s = load_settings(env_file=f, environ={"CREDAGENT_HOME": str(tmp_path / "home")})
    assert s.jev_model == "typesafe/jev-latest"
    assert s.fastrouter_base_url == "https://api.fastrouter.ai/api/v1"
    assert "fake-key-for-test-123" not in repr(s)
    assert "fake-key-for-test-123" not in str(s.describe())
    assert s.describe()["FASTROUTER_API_KEY"] == "set"
    assert s.describe()["TAVILY_API_KEY"] == "missing"


def test_home_inside_repo_refused(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(env_file=tmp_path / "none", environ={"CREDAGENT_HOME": str(REPO_ROOT / "x")})
