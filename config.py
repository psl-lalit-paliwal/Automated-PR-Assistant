"""Configuration loading: config.yaml for settings, environment/.env for secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"


class ConfigError(RuntimeError):
    """Raised when required configuration or a secret is missing."""


@dataclass(frozen=True)
class Settings:
    """Parsed config.yaml plus environment values. Secrets are never logged."""

    raw: dict[str, Any]
    github_token: str
    github_owner: str
    github_repo: str
    bob_api_key: str

    @property
    def mcp_url(self) -> str:
        return self.raw["github"]["mcp_url"]

    @property
    def per_page(self) -> int:
        return int(self.raw["github"].get("per_page", 100))

    @property
    def risk(self) -> dict[str, Any]:
        return self.raw["risk"]

    @property
    def max_reviewers(self) -> int:
        return int(self.raw["reviewers"]["max_suggestions"])

    @property
    def min_age_days(self) -> int:
        return int(self.raw["cleanup"]["min_age_days"])

    @property
    def protected_branches(self) -> list[str]:
        return list(self.raw["cleanup"]["protected_branches"])

    @property
    def output_dir(self) -> Path:
        return ROOT / self.raw["output"]["dir"]

    def __repr__(self) -> str:  # keep secrets out of logs and tracebacks
        return f"Settings(owner={self.github_owner!r}, repo={self.github_repo!r})"


def load_settings(
    config_path: Path = DEFAULT_CONFIG_PATH,
    *,
    require_bob_key: bool = False,
) -> Settings:
    """Load config.yaml and .env. Fails fast if a required secret is missing."""
    load_dotenv(ROOT / ".env")

    with open(config_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    def env(name: str, required: bool = True) -> str:
        value = os.environ.get(name, "").strip()
        if required and not value:
            raise ConfigError(f"Missing environment variable {name} (see .env.example)")
        return value

    return Settings(
        raw=raw,
        github_token=env("GITHUB_TOKEN"),
        github_owner=env("GITHUB_OWNER"),
        github_repo=env("GITHUB_REPO"),
        bob_api_key=env("BOB_API_KEY", required=require_bob_key),
    )
