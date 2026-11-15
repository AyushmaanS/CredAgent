"""Load local configuration from the environment and a git-ignored env file.

Values are never printed. `describe()` reports only whether each key is set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / ".env.local"

DEFAULTS = {
    "FASTROUTER_BASE_URL": "https://api.fastrouter.ai/api/v1",
    "CREDAGENT_LLM_MODEL": "anthropic/claude-sonnet-5.5",
    "CREDAGENT_STAGEHAND_MODEL": "anthropic/claude-haiku-5.5",
    "CREDAGENT_JEV_MODEL": "typesafe/jev-latest",
    # Provisional local placeholder until the owner decides open question Q3 (DECISIONS.md).
    "CREDAGENT_REDIRECT_URI": "http://127.0.0.1:8976/callback",
}
SECRET_KEYS = ("FASTROUTER_API_KEY", "TAVILY_API_KEY")


class ConfigError(Exception):
    """Plain-language configuration problem the owner can fix."""


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. No interpolation, no export, no multi-line values."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    fastrouter_api_key: str = field(repr=False, default="")
    tavily_api_key: str = field(repr=False, default="")
    fastrouter_base_url: str = DEFAULTS["FASTROUTER_BASE_URL"]
    llm_model: str = DEFAULTS["CREDAGENT_LLM_MODEL"]
    stagehand_model: str = DEFAULTS["CREDAGENT_STAGEHAND_MODEL"]
    jev_model: str = DEFAULTS["CREDAGENT_JEV_MODEL"]
    redirect_uri: str = DEFAULTS["CREDAGENT_REDIRECT_URI"]
    home: Path = Path.home() / ".credagent"
    env_file: Path = DEFAULT_ENV_FILE

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    @property
    def profiles_dir(self) -> Path:
        return self.home / "profiles"

    @property
    def secrets_dir(self) -> Path:
        return self.home / "secrets"

    def describe(self) -> dict[str, str]:
        """Non-secret summary safe to print."""
        return {
            "FASTROUTER_API_KEY": "set" if self.fastrouter_api_key else "missing",
            "TAVILY_API_KEY": "set" if self.tavily_api_key else "missing",
            "FASTROUTER_BASE_URL": self.fastrouter_base_url,
            "CREDAGENT_LLM_MODEL": self.llm_model,
            "CREDAGENT_STAGEHAND_MODEL": self.stagehand_model,
            "CREDAGENT_JEV_MODEL": self.jev_model,
            "CREDAGENT_REDIRECT_URI": self.redirect_uri,
            "CREDAGENT_HOME": str(self.home),
            "env file": f"{self.env_file} ({'found' if self.env_file.exists() else 'not found'})",
        }


def load_settings(env_file: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    """Environment variables override the env file; empty values fall back to defaults."""
    # An explicit argument wins over CREDAGENT_ENV_FILE, which wins over the default.
    env_path = Path(env_file) if env_file else Path(os.environ.get("CREDAGENT_ENV_FILE", DEFAULT_ENV_FILE))
    merged = parse_env_file(env_path)
    for key, value in (environ if environ is not None else os.environ).items():
        if value:
            merged[key] = value

    def get(key: str) -> str:
        return merged.get(key) or DEFAULTS.get(key, "")

    home_raw = merged.get("CREDAGENT_HOME") or str(Path.home() / ".credagent")
    home = Path(home_raw).expanduser()
    if is_inside(home, REPO_ROOT):
        raise ConfigError(
            f"CREDAGENT_HOME ({home}) is inside the repository. Run state, browser "
            "profiles and secrets must live outside the repo. Leave CREDAGENT_HOME empty "
            "to use ~/.credagent."
        )
    return Settings(
        fastrouter_api_key=get("FASTROUTER_API_KEY"),
        tavily_api_key=get("TAVILY_API_KEY"),
        fastrouter_base_url=get("FASTROUTER_BASE_URL").rstrip("/"),
        llm_model=get("CREDAGENT_LLM_MODEL"),
        stagehand_model=get("CREDAGENT_STAGEHAND_MODEL"),
        jev_model=get("CREDAGENT_JEV_MODEL"),
        redirect_uri=get("CREDAGENT_REDIRECT_URI"),
        home=home,
        env_file=env_path,
    )
