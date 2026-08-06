"""Environment-driven configuration and secret redaction.

Secrets (VAST_API_KEY, SSH keys) are read only from the environment; nothing is
hardcoded here and nothing is ever written back out. See .env.example.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Redact `api_key=<hex>` anywhere it might appear in an exception/log line so a
# key can never leak into terminal output or a traceback.
_API_KEY_RE = re.compile(r"api_key=[A-Za-z0-9._-]+", re.IGNORECASE)

DEFAULT_REGISTRY = "ghcr.io/bigpick/vast-ai-hashcat-helpers"
DEFAULT_CUDA = "12.9.1"          # must stay <= 13.0 (see design §8)
DEFAULT_HASHCAT_VERSION = "v7.1.2"
DEFAULT_LABEL = "remote-hashcat"
DEFAULT_DISK_GB = 64


def sanitize(text: str) -> str:
    """Strip any API key out of a string before it is shown or logged."""
    return _API_KEY_RE.sub("api_key=REDACTED", text)


def registry() -> str:
    return os.environ.get("REMOTE_HASHCAT_REGISTRY", DEFAULT_REGISTRY)


def cuda_version() -> str:
    return os.environ.get("REMOTE_HASHCAT_CUDA", DEFAULT_CUDA)


def hashcat_version() -> str:
    return os.environ.get("REMOTE_HASHCAT_HASHCAT_VERSION", DEFAULT_HASHCAT_VERSION)


def label() -> str:
    return os.environ.get("REMOTE_HASHCAT_LABEL", DEFAULT_LABEL)


def image_ref() -> str:
    """Fully-qualified worker image, e.g. ghcr.io/bigpick/...:v7.1.2-cuda12.9.1."""
    return f"{registry()}:{hashcat_version()}-cuda{cuda_version()}"


def config_dir() -> Path:
    override = os.environ.get("REMOTE_HASHCAT_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "remote-hashcat"


def cuda_major_minor(version: str | None = None) -> float:
    """'12.9.1' -> 12.9, used to require cuda_max_good >= this on offers."""
    parts = (version or cuda_version()).split(".")
    return float(".".join(parts[:2])) if parts else 0.0
