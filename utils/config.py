"""Configuration loading for the NordRouter image MCP server."""

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

# Absolute path to the server project root (the directory that contains this
# ``utils`` package). Used to locate the local ``.env`` file regardless of the
# process working directory.
SERVER_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(SERVER_ROOT / ".env")

DEFAULT_BASE_URL = "https://nordrouter.net/v1"
DEFAULT_TIMEOUT = 180.0

# The gateway safety filter is ON by default on the server side. This MCP server
# always sends ``safety_filter: false`` so that requests are not rejected by the
# gateway moderation layer; the caller takes responsibility for the prompts.
DEFAULT_SAFETY_FILTER = False

_TRUE_VALUES = {"1", "true", "yes", "on"}


DEFAULT_USD_RUB = 95.0


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the server."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    project_root: Path = Path.cwd()
    usd_rub: float = DEFAULT_USD_RUB

    safety_filter: bool = DEFAULT_SAFETY_FILTER


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable (``true``/``1``/``yes``/``on``)."""
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def get_config() -> Config:
    """Load configuration from environment variables and the local ``.env``."""
    api_key = _env("NORDROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "NORDROUTER_API_KEY is not set. Add it to .env or to the MCP server "
            "configuration (env block) before starting the server."
        )

    base_url = (_env("NORDROUTER_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
    timeout = float(_env("NORDROUTER_TIMEOUT", str(DEFAULT_TIMEOUT)) or DEFAULT_TIMEOUT)
    project_root = Path(
        _env("NORDROUTER_PROJECT_ROOT", str(Path.cwd())) or str(Path.cwd())
    ).expanduser().resolve()

    return Config(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        project_root=project_root,
        usd_rub=float(_env("NORDROUTER_USD_RUB", str(DEFAULT_USD_RUB)) or DEFAULT_USD_RUB),

        safety_filter=_env_bool("NORDROUTER_SAFETY_FILTER", DEFAULT_SAFETY_FILTER),
    )
