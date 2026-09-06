from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlsplit


class UnsafeEvidenceError(RuntimeError):
    pass


_SECRET_KEY_FRAGMENTS = (
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "api_key",
    "apikey",
    "client_secret",
)


def _looks_secret_key(value: str) -> bool:
    normalized = value.lower().replace("-", "_")
    return any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS)


def ensure_safe_evidence(value: Any, path: str = "evidence") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _looks_secret_key(str(key)):
                raise UnsafeEvidenceError(f"credential-like key is forbidden at {path}.{key}")
            ensure_safe_evidence(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            ensure_safe_evidence(child, f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return

    lowered = value.lower().strip()
    if lowered.startswith("bearer ") or "authorization: bearer" in lowered:
        raise UnsafeEvidenceError(f"credential-like bearer value is forbidden at {path}")
    if "access_token=" in lowered or "refresh_token=" in lowered:
        raise UnsafeEvidenceError(f"credential-bearing string is forbidden at {path}")
    if lowered.startswith(("http://", "https://")):
        for key, _ in parse_qsl(urlsplit(value).query, keep_blank_values=True):
            if _looks_secret_key(key):
                raise UnsafeEvidenceError(f"credential-bearing URL is forbidden at {path}")
