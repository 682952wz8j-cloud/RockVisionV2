"""Publisher CAM configuration. Separate from backend runtime read identity.

Reads CRAGPAL_PUBLISHER_* only. Never TENCENT_* runtime keys.
Never logs SecretId / SecretKey / tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REQUIRED_ENV = (
    "CRAGPAL_PUBLISHER_COS_REGION",
    "CRAGPAL_PUBLISHER_SECRET_ID",
    "CRAGPAL_PUBLISHER_SECRET_KEY",
    "CRAGPAL_PUBLISHER_COS_BUCKET",
)

FORBIDDEN_RUNTIME_ENV = (
    "TENCENT_SECRET_ID",
    "TENCENT_SECRET_KEY",
    "TENCENT_COS_REGION",
    "TENCENT_COS_BUCKET",
)

SECRET_ENV_NAMES = frozenset(
    {
        "CRAGPAL_PUBLISHER_SECRET_ID",
        "CRAGPAL_PUBLISHER_SECRET_KEY",
        "TENCENT_SECRET_ID",
        "TENCENT_SECRET_KEY",
    }
)

DEFAULT_ENV_FILE = Path.home() / ".config" / "cragpal" / "publisher.env"
ENV_FILE_VAR = "CRAGPAL_PUBLISHER_ENV_FILE"


class PublisherConfigError(ValueError):
    """Publisher identity is missing or is the runtime read CAM."""


@dataclass(frozen=True)
class PublisherConfig:
    region: str
    secret_id: str
    secret_key: str
    bucket: str

    def __repr__(self) -> str:
        return (
            "PublisherConfig(region='***', secret_id='***', secret_key='***', bucket='***')"
        )


def resolve_env_file(environ: dict[str, str], *, default_if_exists: bool = False) -> Path | None:
    raw = environ.get(ENV_FILE_VAR)
    if raw:
        return Path(raw).expanduser()
    if default_if_exists and DEFAULT_ENV_FILE.is_file():
        return DEFAULT_ENV_FILE
    return None


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def load_publisher_config(
    environ: dict[str, str],
    *,
    env_file: Path | None = None,
) -> PublisherConfig:
    merged = dict(environ)
    if env_file is not None:
        merged.update(load_env_file(env_file))
    missing = [name for name in REQUIRED_ENV if not merged.get(name)]
    if missing:
        raise PublisherConfigError(
            "publisher CAM configuration missing; runtime TENCENT_* identity is not a publisher identity"
        )
    return PublisherConfig(
        region=merged[REQUIRED_ENV[0]],
        secret_id=merged[REQUIRED_ENV[1]],
        secret_key=merged[REQUIRED_ENV[2]],
        bucket=merged[REQUIRED_ENV[3]],
    )


def redact_text(text: str, environ: dict[str, str] | None = None) -> str:
    """Remove known secret values from a string. Used by tests and CLI guards."""
    redacted = text
    if environ:
        for name in SECRET_ENV_NAMES:
            value = environ.get(name)
            if value:
                redacted = redacted.replace(value, "***")
    return redacted
